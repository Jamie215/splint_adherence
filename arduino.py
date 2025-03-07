import csv
import io
import os
import time
import datetime
from typing import Optional, Tuple, Dict, Any, Union

import serial
import serial.tools.list_ports

# Constants for serial communication
BAUD_RATE = 115200
TIMEOUT = 5  # seconds
READ_TIMEOUT = 10  # seconds for longer operations like data download
DEBUG_TIMEOUT = 20  # longer timeout for capturing debug messages

# Command prefixes and response identifiers
CMD_PREFIX = "CMD:"
RESP_PREFIX = "RESP:"
DATA_PREFIX = "DATA:"

# Command types
CMD_STATUS = "STATUS"
CMD_INIT = "INIT"
CMD_RETRIEVE = "RETRIEVE"
CMD_DISCONNECT = "DISCONNECT"

# Response types
RESP_OK = "OK"
RESP_ERROR = "ERROR"
DATA_BEGIN = "BEGIN"
DATA_END = "END"

# Global serial connection
arduino_serial = None

def find_arduino_port() -> Optional[str]:
    """
    Find the port to which the Arduino is connected.
    Returns the port name or None if no suitable device is found.
    """
    available_ports = list(serial.tools.list_ports.comports())
    
    # If there's only one port, use it
    if len(available_ports) == 1:
        return available_ports[0].device
    
    # Otherwise, try to identify an Arduino port
    arduino_identifiers = ['arduino', 'USB Serial Device', 'usbmodem', 'ttyACM', 'ttyUSB']
    for port in available_ports:
        if any(identifier.lower() in port.description.lower() for identifier in arduino_identifiers):
            return port.device
            
    # Return the first port if we can't specifically identify an Arduino
    return available_ports[0].device if available_ports else None

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
    
    # Find Arduino port
    port = find_arduino_port()
    if not port:
        return False, "No Arduino device found"
    
    try:
        # Open serial connection
        arduino_serial = serial.Serial(port, BAUD_RATE, timeout=TIMEOUT)
        time.sleep(2)  # Give Arduino time to reset after connection
        
        # Clear any pending data
        if arduino_serial.in_waiting:
            arduino_serial.reset_input_buffer()
            
        return True, f"Connected to Arduino on {port}"
    except Exception as e:
        return False, f"Failed to connect: {str(e)}"

def send_command(command: str, payload: str = "") -> Tuple[bool, str]:
    """
    Send a command to the Arduino.
    command: The command to send (STATUS, INIT, RETRIEVE)
    payload: Optional payload data for the command
    Returns a tuple: (success, response or error message)
    """
    global arduino_serial
    
    if not arduino_serial or not arduino_serial.is_open:
        return False, "Not connected to Arduino"
    
    try:
        # Format the command
        cmd = f"{CMD_PREFIX}{command};"
        if payload:
            cmd += payload
        cmd += "\r\n"
        
        # Clear input buffer before sending command
        arduino_serial.reset_input_buffer()
        
        # Send the command
        arduino_serial.write(cmd.encode())
        arduino_serial.flush()
        
        # Wait for response
        start_time = time.time()
        response = ""

        while True:
            if time.time() - start_time > TIMEOUT:
                return False, "Timeout waiting for response"
            if arduino_serial.in_waiting == 0:
                time.sleep(0.1)
                continue

            line = arduino_serial.readline().decode().strip()

            # Skip debug and info messages
            if line.startswith("[DEBUG]") or line.startswith("[INFO]") or line.startswith("[BOOT]"):
                print(f"Debug message: {line}")
                continue
                
            # Check for proper response
            if line.startswith(RESP_PREFIX):
                response = line
                break
                
            # If we get here, we received something unexpected
            if line:
                return False, f"Unexpected response: {line}"
                
        # Parse response
        if response.startswith(RESP_PREFIX):
            parts = response[len(RESP_PREFIX):].split(';')
            status = parts[0]
            data = parts[1] if len(parts) > 1 else ""
            
            if status == RESP_OK:
                return True, data
            elif status == RESP_ERROR:
                return False, f"Arduino error: {data}"
        
        return False, f"Unexpected response: {response}"
    except Exception as e:
        return False, f"Command error: {str(e)}"

def get_device_status() -> bytes:
    """
    Check the status of the Arduino device.
    Returns the status as bytes (for compatibility with existing code).
    """
    # Connect if not already connected
    if not arduino_serial or not arduino_serial.is_open:
        success, _ = connect_to_arduino()
        if not success:
            return b"DISCONNECTED"
    
    # Send status command
    success, response = send_command(CMD_STATUS)
    if success:
        if "CONFIGURED" in response:
            return b"CONNECTED"
        elif "NOT_CONFIGURED" in response:
            return b"CONNECTED"
        elif "HAS_DATA" in response:
            return b"CONNECTED"
        else:
            return response.encode()
    
    return b"ERROR"

def read_debug_messages(timeout_seconds=DEBUG_TIMEOUT) -> str:
    """
    Read all available debug messages from the Arduino.
    Continues reading until timeout or connection is lost.
    
    Returns:
        A string containing all captured messages.
    """
    if not arduino_serial or not arduino_serial.is_open:
        return "Error: Not connected to Arduino"
    
    # Set a longer timeout for debug reading
    original_timeout = arduino_serial.timeout
    arduino_serial.timeout = 1.0  # Short timeout for readline, but we'll loop
    
    messages = []
    start_time = time.time()
    
    print("Reading debug messages... (press Ctrl+C to stop)")
    
    try:
        # Read messages until timeout or connection lost
        while time.time() - start_time < timeout_seconds:
            try:
                if arduino_serial.in_waiting > 0:
                    line = arduino_serial.readline().decode('utf-8', errors='replace').strip()
                    if line:
                        print(f"DEBUG: {line}")
                        messages.append(line)
                        # Reset timeout if we're still receiving data
                        if "[DEBUG]" in line or "[STATUS]" in line:
                            start_time = time.time()
                else:
                    time.sleep(0.1)
            except Exception as e:
                print(f"Communication interrupted: {e}")
                messages.append(f"--- Communication interrupted: {e} ---")
                break
    except KeyboardInterrupt:
        messages.append("--- Debug capture stopped by user ---")
    finally:
        # Restore original timeout
        if arduino_serial and arduino_serial.is_open:
            arduino_serial.timeout = original_timeout
    
    return "\n".join(messages)

def initialize_arduino(epoch_time: int, personal_id: Union[int, str], wakeup_interval: int) -> Tuple[bool, str]:
    """
    Initialize the Arduino with timestamp, personal ID, and wake-up interval.
    Captures and returns detailed debug information.
    
    Returns:
        Tuple: (success, debug_output)
    """
    # Connect if not already connected
    if not arduino_serial or not arduino_serial.is_open:
        success, message = connect_to_arduino()
        if not success:
            return False, f"Failed to connect to Arduino: {message}"
    
    if isinstance(personal_id, int):
        personal_id = str(personal_id)
    
    # Step 1: Send initialization command to prepare Arduino
    success, response = send_command(CMD_INIT)
    if not success:
        return False, f"Failed to prepare Arduino for initialization: {response}"
    
    # The "SET_FOR_LOGGING" response means Arduino is waiting for initialization data
    if "READY_FOR_INIT" not in response:
        return False, f"Unexpected response preparing for initialization: {response}"
    
    debug_output = [f"Arduino is ready for initialization data. Response: {response}"]
    
    # Step 2: Send initialization data
    try:
        # Send initialization data directly in the format Arduino expects
        init_payload = f"<{epoch_time},{personal_id},{wakeup_interval}>"
        success, response = send_command(CMD_INIT, init_payload)
        if not success:
            return False, f"Failed to initialize Arduino: {response}"
        
        debug_output.append(f"Initialization data sent: {init_payload}")

        if success and "INITIALIZED" in response:
            debug_output.append("Device successfully prepared for logging mode")
            
        else:
            debug_output.append(f"Warning: Device may not have transitioned properly: {response}")

        return True, "\n".join(debug_output)
        
    except Exception as e:
        # Check if this is the expected disconnect due to Arduino shutting down
        if ("PermissionError" in str(e) or "device disconnected" in str(e) or 
            "ClearCommError" in str(e) or "device not recognized" in str(e)):
            # This is normal - the Arduino has shut down as expected
            debug_output.append(f"Device disconnected during shutdown sequence (expected behavior): {e}")
            return True, "\n".join(debug_output)
        
        # This is an unexpected error
        return False, f"Failed to send initialization data: {str(e)}"
    finally:
        # Always disconnect after initialization
        disconnect_arduino()

def download_file(file_path: str) -> Dict[str, Any]:
    """
    Download data from the Arduino and save it to a file.
    Returns a dictionary with the data for the Dash download component.
    """
    # Connect if not already connected
    if not arduino_serial or not arduino_serial.is_open:
        success, message = connect_to_arduino()
        if not success:
            raise Exception(f"Failed to connect to Arduino: {message}")
    
    # Set longer timeout for data retrieval
    original_timeout = arduino_serial.timeout
    arduino_serial.timeout = READ_TIMEOUT
    
    try:
        # Clear any pending data in the buffer
        if arduino_serial.in_waiting:
            arduino_serial.reset_input_buffer()

        # Send retrieve command
        success, response = send_command(CMD_RETRIEVE)
        if not success:
            raise Exception(f"Failed to retrieve data: {response}")
        
        # Read metadata and data
        metadata = {}
        data_points = []
        in_data_section = False
        
        # Process response lines
        while True:
            line = arduino_serial.readline().decode().strip()
            if not line:
                continue

            if line.startswith("[DEBUG]") or line.startswith("[INFO]"):
                print(f"Debug: {line}")
                continue
                
            # Check for metadata
            if ':' in line and not line.startswith(DATA_PREFIX) and not in_data_section:
                key, value = line.split(':', 1)
                if key == "Initial Timestamp":
                    epoch_time = int(value)
                    formatted_time = datetime.datetime.fromtimestamp(epoch_time, tz=datetime.timezone.utc)
                    formatted_time = formatted_time.strftime("%Y-%m-%d %H:%M:%S")
                    metadata[key] = formatted_time
                else:
                    metadata[key] = value
                continue
                
            # Check for data section start
            if line == f"{DATA_PREFIX}{DATA_BEGIN};":
                in_data_section = True
                continue
                
            # Check for data section end
            if line == f"{DATA_PREFIX}{DATA_END};":
                break
                
            # Process data point if in data section
            if in_data_section and ',' in line:
                try:
                    index, temp = line.split(',')
                    data_points.append((int(index), float(temp)))
                except ValueError:
                    # Skip malformed lines
                    continue
        
        # Calculate timestamps for each data point
        timestamped_data = []
        wakeup_interval = int(metadata.get('Wake-up Interval', 0))

        for index, temp in data_points:
            timestamp = epoch_time + (index*wakeup_interval)
            formatted_timestamp = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
            formatted_timestamp = formatted_timestamp.strftime("%Y-%m-%d %H:%M:%S")
            timestamped_data.append((formatted_timestamp, temp))
        
        # Create CSV in memory
        csv_buffer = io.StringIO()
        csv_writer = csv.writer(csv_buffer)
        
        # Write headers
        csv_writer.writerow(['Initial Timestamp', metadata.get('Initial Timestamp', 'N/A')])
        csv_writer.writerow(['Wake-up Interval (Seconds)', metadata.get('Wake-up Interval', 'N/A')])
        csv_writer.writerow(['Personal ID', metadata.get('Personal ID', 'N/A')])
        csv_writer.writerow([])  # Empty row
        csv_writer.writerow(['Timestamp', 'Temperature (C)'])
        
        # Write data points
        for timestamp, temp in timestamped_data:
            csv_writer.writerow([timestamp, temp])
        
        # Save to file
        with open(file_path, 'w', newline='') as f:
            f.write(csv_buffer.getvalue())
        
        # Prepare return data for Dash download
        return {
            'content': csv_buffer.getvalue(),
            'filename': os.path.basename(file_path),
            'type': 'text/csv'
        }
            
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