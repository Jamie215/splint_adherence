import io
import time
import datetime
import struct
from typing import Optional, Dict, Any, Tuple, Union

import serial
import serial.tools.list_ports

# Constants for serial communication
BAUD_RATE = 115200
TIMEOUT = 5  # seconds
READ_TIMEOUT = 10  # seconds for longer operations like data download


class ArduinoClient:
    """
    Encapsulates the serial connection to the Arduino splint-adherence logger
    and the handshake/init/download protocol.

    The connection state lives on the instance rather than in module globals,
    which keeps the connect-if-needed logic in one place (`_ensure_connected`)
    and makes the client testable in isolation (a fake `serial.Serial` can be
    injected).
    """

    def __init__(self, baud_rate: int = BAUD_RATE, timeout: int = TIMEOUT,
                 read_timeout: int = READ_TIMEOUT):
        self.baud_rate = baud_rate
        self.timeout = timeout
        self.read_timeout = read_timeout
        self._serial: Optional[serial.Serial] = None

    @property
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def _search(self) -> Optional[serial.Serial]:
        """
        Search the available ports for the Arduino using a simple handshake.
        Returns an open Serial object if found, otherwise None.
        """
        available_ports = [port.device for port in serial.tools.list_ports.comports()]

        for port in available_ports:
            ser = None
            try:
                ser = serial.Serial(port, self.baud_rate, timeout=self.timeout)
                time.sleep(2)  # Give Arduino time to reset after connection

                # Clear any pending data
                ser.reset_input_buffer()

                # Send handshake request
                ser.write(b"?")
                response = ser.readline().strip()

                if response == b"Hello World!":
                    print(f"Arduino found on port {port}")
                    return ser

                # Not a recognized device, close and try next port
                ser.close()

            except serial.SerialException:
                # Move to next port on error
                if ser is not None and ser.is_open:
                    ser.close()

        return None

    def connect(self) -> Tuple[bool, str]:
        """
        Attempt to connect to the Arduino device.
        Returns a tuple: (success, message)
        """
        # If already connected, close it first to ensure a clean connection
        if self.is_connected:
            self._serial.close()
            time.sleep(1)  # Give it time to close properly

        self._serial = self._search()
        if not self._serial:
            return False, "No Arduino device found"

        return True, f"Connected to Arduino on {self._serial.port}"

    def _ensure_connected(self) -> Tuple[bool, str]:
        """
        Ensure there is an open connection, connecting if necessary.
        Returns a tuple: (success, message)
        """
        if self.is_connected:
            return True, "Already connected"
        return self.connect()

    def get_status(self) -> bytes:
        """
        Check the status of the Arduino device.
        Returns the status as bytes.
        """
        success, _ = self._ensure_connected()
        if not success:
            return b"DISCONNECTED"

        try:
            # Send status request
            self._serial.reset_input_buffer()
            self._serial.write(b"!")
            response = self._serial.readline().strip()

            if not response:
                return b"ERROR"

            print(f"Status response: {response}")
            return response

        except Exception as e:
            print(f"Error getting status: {e}")
            # If error occurs, drop the connection so the next call reconnects
            self.disconnect()
            return b"ERROR"

    def initialize(self, epoch_time: int, personal_id: Union[int, str] = "",
                   wakeup_interval: int = 300) -> Tuple[bool, str]:
        """
        Initialize the Arduino with timestamp, ID and wakeup interval.

        Returns:
            Tuple: (success, debug_output)
        """
        # Convert personal_id to string if it's an integer
        personal_id = str(personal_id) if isinstance(personal_id, int) else personal_id

        # Check for timestamp overflow and warn
        if epoch_time >= 2**32:
            print("Warning: Timestamp exceeds 32-bit limit, will be truncated on device")

        success, message = self._ensure_connected()
        if not success:
            return False, f"Failed to connect to Arduino: {message}"

        try:
            # Send initialization command
            self._serial.reset_input_buffer()
            self._serial.write(b"i")
            time.sleep(0.5)
            response = self._serial.readline().strip()
            print(f"Initialization response: {response}")

            if response != b"READY_FOR_INIT":
                return False, f"Unexpected response: {response}"

            # Ensure personal_id is exactly 16 bytes, null-padded
            id_bytes = personal_id.encode('utf-8')
            if len(id_bytes) > 15:  # Allow space for null terminator
                id_bytes = id_bytes[:15]
            id_bytes = id_bytes.ljust(16, b'\0')

            # Pack data:
            # uint32_t timestamp (4 bytes)
            # uint32_t wakeup_interval (4 bytes)
            # char[16] personal_id (16 bytes)
            # uint32_t checksum (4 bytes)
            fmt = "<II16sI"

            # Use 32-bit timestamp (truncate if needed)
            timestamp_32bit = epoch_time & 0xFFFFFFFF

            # Calculate simple checksum (sum of all bytes in other fields)
            data_to_checksum = struct.pack("<II16s", timestamp_32bit, wakeup_interval, id_bytes)
            checksum = sum(data_to_checksum) & 0xFFFFFFFF

            # Pack all data with checksum
            packed_data = struct.pack(fmt, timestamp_32bit, wakeup_interval, id_bytes, checksum)

            # Send the packed data
            self._serial.write(packed_data)

            # Wait for response (this might not come due to shutdown)
            start_time = time.time()
            response = b""
            while time.time() - start_time < 5:
                if self._serial.in_waiting:
                    response = self._serial.readline().strip()
                    if response:
                        print(f"Final response: {response}")
                        break
                time.sleep(0.1)
            # Delay to wait for Arduino to be SystemOFF
            time.sleep(3)
            return True, "Device initialized successfully"

        except Exception as e:
            # Check if this is the expected disconnect due to Arduino shutting down
            if ("PermissionError" in str(e) or "device disconnected" in str(e) or
                    "ClearCommError" in str(e) or "device not recognized" in str(e)):
                # This is normal - the Arduino has shut down as expected
                return True, f"Device disconnected during shutdown sequence (expected behavior): {e}"

            # This is an unexpected error
            return False, f"Failed to initialize Arduino: {str(e)}"
        finally:
            # Always disconnect after initialization
            self.disconnect()

    def download(self, filename: str) -> Dict[str, Any]:
        """
        Download data from the Arduino and return it for the Dash download
        component. Preserves the original CSV format with metadata at the top.

        Args:
            filename: name of the file

        Returns:
            A dictionary with the data for the Dash download component.
        """
        success, message = self._ensure_connected()
        if not success:
            raise Exception(f"Failed to connect to Arduino: {message}")

        original_timeout = self._serial.timeout
        try:
            # Set longer timeout for download
            self._serial.timeout = self.read_timeout

            self._serial.reset_input_buffer()
            self._serial.write(b"r")

            # Buffer to collect all decoded/processed CSV text
            output_buffer = io.StringIO()

            # Buffer to accumulate raw data from serial
            data_buffer = bytearray()

            in_metadata = True  # Start in metadata section
            END_DATA_MARKER = b"END_DATA"

            # Read data in chunks
            start_time = time.time()
            while True:
                # Read a chunk of data
                chunk = self._serial.read(min(4096, max(1, self._serial.in_waiting)))
                if not chunk:
                    # If no data and we've been reading for a while, timeout
                    if time.time() - start_time > self.read_timeout:
                        raise TimeoutError("Timeout waiting for data")
                    time.sleep(0.1)
                    continue

                # Add to buffer
                data_buffer.extend(chunk)

                # Check if we have the end marker
                if END_DATA_MARKER in data_buffer:
                    # Found the end marker, process remaining data and exit
                    end_idx = data_buffer.find(END_DATA_MARKER)
                    valid_data = data_buffer[:end_idx]

                    # Process lines up to the marker
                    self._process_buffer_data(valid_data, output_buffer, in_metadata)
                    break

                # Process complete lines from buffer
                if b'\r\n' in data_buffer:
                    # Split on line endings
                    lines = data_buffer.split(b'\r\n')
                    # Keep the last (possibly incomplete) line
                    last_line = lines.pop()

                    # Process all complete lines
                    complete_data = b'\r\n'.join(lines) + b'\r\n'
                    in_metadata = self._process_buffer_data(complete_data, output_buffer, in_metadata)

                    # Keep only the incomplete line in the buffer
                    data_buffer = last_line

            return {
                'content': output_buffer.getvalue(),
                'filename': filename,
                'type': 'text/csv'
            }
        except Exception as e:
            print(f"Error downloading file: {e}")
            raise Exception(f"Failed to download data: {str(e)}")
        finally:
            # Restore original timeout
            if self.is_connected:
                self._serial.timeout = original_timeout

    @staticmethod
    def _process_buffer_data(data: bytearray, output: io.StringIO, in_metadata: bool) -> bool:
        """
        Process a chunk of data from the Arduino.

        Args:
            data: Buffer of data to process
            output: StringIO buffer to write processed data to
            in_metadata: Whether we're in the metadata section

        Returns:
            Updated in_metadata state
        """
        # Split into lines
        lines = data.split(b'\r\n')

        # Process each line
        for line in lines:
            if not line:  # Skip empty lines
                continue

            # Try to decode line with error handling
            try:
                line_str = line.decode('utf-8').strip()
            except UnicodeDecodeError:
                # Skip lines that can't be decoded properly
                print(f"Warning: Skipping non-UTF-8 line of length {len(line)}")
                continue

            # Process the line according to state
            if in_metadata:
                if line_str.startswith("Timestamp,Temperature,ProximityVal"):
                    # Found header line, switch to data mode
                    in_metadata = False
                    output.write("Timestamp,Temperature,ProximityVal\r\n")
                elif line_str.startswith("Initial Timestamp,"):
                    # Process timestamp in metadata
                    parts = line_str.split(',', 1)
                    if len(parts) > 1 and parts[1].strip().isdigit():
                        # Convert timestamp to readable format
                        epoch_time = int(parts[1].strip())
                        iso_time = datetime.datetime.fromtimestamp(
                            epoch_time, tz=datetime.timezone.utc
                        ).strftime('%Y-%m-%d %H:%M:%S')
                        output.write(f"Initial Timestamp,{iso_time}\r\n")
                    else:
                        # Keep original line if conversion fails
                        output.write(f"{line_str}\r\n")
                else:
                    # Other metadata lines
                    output.write(f"{line_str}\r\n")
            else:
                # Data section
                parts = line_str.split(',')
                if len(parts) == 3 and parts[0].strip().isdigit():
                    # It's a data line with timestamp
                    try:
                        epoch_time = int(parts[0].strip())
                        iso_time = datetime.datetime.fromtimestamp(
                            epoch_time, tz=datetime.timezone.utc
                        ).strftime('%Y-%m-%d %H:%M:%S')
                        output.write(f"{iso_time},{parts[1]},{parts[2]}\r\n")
                    except (ValueError, OverflowError) as e:
                        # Handle invalid timestamps
                        print(f"Warning: Invalid timestamp {parts[0]}: {e}")
                        output.write(f"{line_str}\r\n")
                else:
                    # Non-data line in data section
                    output.write(f"{line_str}\r\n")

        return in_metadata

    def disconnect(self) -> None:
        """Disconnect from the Arduino device."""
        if self.is_connected:
            self._serial.close()
            print("Arduino disconnected successfully")
        self._serial = None


# Shared client instance used across the app.
client = ArduinoClient()
