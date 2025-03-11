import csv
import io
import os
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

# Global serial connection
arduino_serial = None

def search_for_arduino() -> Optional[serial.Serial]:
    """
    Search for the Arduino device with a simple handshake protocol.
    Returns a Serial object if device is found, None otherwise.
    """
    available_ports = [port.device for port in serial.tools.list_ports.comports()]
    
    for port in available_ports:
        try:
            ser = serial.Serial(port, BAUD_RATE, timeout=TIMEOUT)
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
            if 'ser' in locals() and ser.is_open:
                ser.close()
                
    return None

def connect_to_arduino() -> Tuple[bool, str]:
    """
    Attempt to connect to the Arduino device.
    Returns a tuple: (success, message)
    """
    global arduino_serial
    
    # If already connected, close it first to ensure a clean connection
    if arduino_serial and arduino_serial.is_open:
        arduino_serial.close()
        time.sleep(1)  # Give it time to close properly
    
    # Search for Arduino
    arduino_serial = search_for_arduino()
    if not arduino_serial:
        return False, "No Arduino device found"
    
    return True, f"Connected to Arduino on {arduino_serial.port}"

def get_device_status() -> bytes:
    """
    Check the status of the Arduino device.
    Returns the status as bytes.
    """
    global arduino_serial
    
    # Connect if not already connected
    if not arduino_serial or not arduino_serial.is_open:
        success, _ = connect_to_arduino()
        if not success:
            return b"DISCONNECTED"
    
    try:
        # Send status request
        arduino_serial.reset_input_buffer()
        arduino_serial.write(b"!")
        response = arduino_serial.readline().strip()
        
        if not response:
            return b"ERROR"
            
        print(f"Status response: {response}")
        return response
        
    except Exception as e:
        print(f"Error getting status: {e}")
        # If error occurs, try to close and reopen the connection
        if arduino_serial and arduino_serial.is_open:
            arduino_serial.close()
        arduino_serial = None
        return b"ERROR"

def initialize_arduino(epoch_time: int, personal_id: Union[int, str] = "", wakeup_interval: int = 30) -> Tuple[bool, str]:
    """
    Initialize the Arduino with timestamp, ID and wakeup interval
    
    Returns:
        Tuple: (success, debug_output)
    """
    global arduino_serial

    # Convert personal_id to string if it's an integer
    personal_id = str(personal_id) if isinstance(personal_id, int) else personal_id
    
    # Check for timestamp overflow and warn
    if epoch_time >= 2**32:
        print("Warning: Timestamp exceeds 32-bit limit, will be truncated on device")
    
    # Connect if not already connected
    if not arduino_serial or not arduino_serial.is_open:
        success, message = connect_to_arduino()
        if not success:
            return False, f"Failed to connect to Arduino: {message}"
    
    try:
        # Send initialization command
        arduino_serial.reset_input_buffer()
        arduino_serial.write(b"i")
        time.sleep(0.5)
        response = arduino_serial.readline().strip()
        print(f"Initialization response: {response}")
        
        if response != b"READY_FOR_INIT":
            return False, f"Unexpected response: {response}"
        
        # Create format string for packing
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
        arduino_serial.write(packed_data)

        # Wait for response (this might not come due to shutdown)
        start_time = time.time()
        response = b""
        while time.time() - start_time < 5:
            if arduino_serial.in_waiting:
                response = arduino_serial.readline().strip()
                if response:
                    print(f"Final response: {response}")
                    break
            time.sleep(0.1)
        
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
        disconnect_arduino()

def download_file(file_path: str) -> Dict[str, Any]:
    """
    Download data from the Arduino and save it to a file.
    
    Args:
        file_path: Path to save the data
        
    Returns:
        A dictionary with the data for the Dash download component.
    """
    global arduino_serial
    
    # Connect if not already connected
    if not arduino_serial or not arduino_serial.is_open:
        success, message = connect_to_arduino()
        if not success:
            raise Exception(f"Failed to connect to Arduino: {message}")
    
    try:
        # Set longer timeout for download
        original_timeout = arduino_serial.timeout
        arduino_serial.timeout = READ_TIMEOUT
        
        # Temporary file for raw data
        temp_file_path = file_path + ".temp"

        arduino_serial.reset_input_buffer()
        arduino_serial.write(b"r")

        # Define end marker for data transmission
        end_data_marker = b"END_DATA"
        marker_position = 0
        
        with open(temp_file_path, "wb") as file:
            # Wait for data to become available (with timeout)
            start_time = time.time()
            while arduino_serial.in_waiting == 0:
                if time.time() - start_time > READ_TIMEOUT:
                    raise TimeoutError("Timeout waiting for data from Arduino")
                time.sleep(0.1)

            data_buffer = bytearray()
            data_in_buffer = False

            # Continuously read the data until the end marker is found
            while True:
                if arduino_serial.in_waiting > 0:
                    data = arduino_serial.read(1024)
                    print(f"Received {len(data)} bytes of data")
                    
                    for byte in data:
                        # Check for the end of marker sequence
                        if byte == end_data_marker[marker_position]:
                            data_buffer.append(byte)
                            data_in_buffer = True
                            marker_position += 1
                            if marker_position == len(end_data_marker):
                                break
                        else:
                            marker_position = 0
                            if data_in_buffer:
                                file.write(data_buffer)
                                data_in_buffer = False
                                data_buffer.clear()
                            file.write(bytes([byte]))

                    if marker_position == len(end_data_marker):
                        break
        
        converted_lines = []
        metadata_lines = []
        found_header = False

        with open(temp_file_path, 'r') as file:
            for line in file:
                line = line.strip()

                if not found_header:
                    if line.startswith("Timestamp,"):
                        # Found the header line
                        found_header = True
                        converted_lines.append("Timestamp,Temperature")
                    else:
                        # Still in metadata section
                        if line.startswith("Initial Timestamp,"):
                            parts = line.split(',',1)
                            if len(parts) == 2 and parts[1].strip().isdigit():
                                # Convert Initial Timestamp to ISO format
                                epoch_time = int(parts[1].strip())
                                iso_time = datetime.datetime.fromtimestamp(
                                    epoch_time, 
                                    tz=datetime.timezone.utc
                                ).strftime('%Y-%m-%d %H:%M:%S')
                                metadata_lines.append(f"Initial Timestamp,{iso_time}")
                            else:
                                metadata_lines.append(line)
                        else:
                            metadata_lines.append(line)
                else:
                    # In data section, check if this is a data line with timestamp
                    parts = line.split(',', 1)
                    if len(parts) == 2 and parts[0].strip().isdigit():
                        # Convert epoch timestamp to ISO format
                        epoch_time = int(parts[0].strip())
                        iso_time = datetime.datetime.fromtimestamp(
                            epoch_time,
                            tz=datetime.timezone.utc
                        ).strftime('%Y-%m-%d %H:%M:%S')
                        converted_lines.append(f"{iso_time},{parts[1]}")
                    else:
                        # Not a data line, keep as is
                        converted_lines.append(line)
        
        # Write processed data to the actual output file
        with open(file_path, 'w', newline='') as file:
            # Write metadata
            for line in metadata_lines:
                file.write(line + '\r\n')
            
            # Add blank line between metadata and data
            if metadata_lines:
                file.write('\r\n')
            
            # Write converted data
            for line in converted_lines:
                file.write(line + '\r\n')
        
        # Delete temporary file
        os.remove(temp_file_path)
        
        # Read the processed file
        with open(file_path, 'r') as f:
            csv_content = f.read()
            
        return {
            'content': csv_content,
            'filename': os.path.basename(file_path),
            'type': 'text/csv'
        }
                
    except Exception as e:
        print(f"Error downloading file: {e}")
        raise Exception(f"Failed to download data: {str(e)}")
            
    finally:
        # Restore original timeout
        if arduino_serial and arduino_serial.is_open:
            arduino_serial.timeout = original_timeout

def disconnect_arduino() -> None:
    """
    Disconnect from the Arduino device.
    """
    global arduino_serial
    
    if arduino_serial and arduino_serial.is_open:
        arduino_serial.close()
        arduino_serial = None
        print("Arduino disconnected successfully")