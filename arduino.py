# Import libraries
import time
from datetime import datetime, timezone, timedelta
import serial
from serial.tools import list_ports

baud_rate = 115200
arduino_serial = None

def find_arduino_port():
    """
    Search for arduino port for making serial connection
    """
    ports = [port.device for port in list_ports.comports()]
    if not ports:
        raise Exception("No available ports found!")
    return ports[0]

def connect_arduino():
    """
    Establish a serial connection with the Arduino.
    """
    global arduino_serial
    try:
        arduino_port = find_arduino_port()
        arduino_serial = serial.Serial(arduino_port, baud_rate, timeout=2)
        time.sleep(2)
        print("[INFO] Arduino connected.")
    except Exception as e:
        print(f"[ERROR] Failed to connect to Arduino: {e}")
        arduino_serial = None

def disconnect_arduino():
    """
    Disconnect Arduino serial connection
    """
    global arduino_serial
    if arduino_serial and arduino_serial.is_open:
        arduino_serial.close()
        arduino_serial = None
        print("[INFO] Arduino disconnected successfully")

def get_device_status():
    """
    Check if the Arduino is ready for initialization or data retrieval.
    """
    global arduino_serial
    if not arduino_serial or not arduino_serial.is_open:
        connect_arduino()

    try:
        arduino_serial.write(b's\n')  # Send a status check command
        time.sleep(1)
        response = arduino_serial.readline().decode('utf-8').strip()
        print(f"[INFO] Arduino response: {response}")
        return response.encode('utf-8')
    except Exception as e:
        print(f"[ERROR] Failed to get Arduino status: {e}")
        return b''
    
def initialize_arduino(epoch_time, personal_id, wakeup_interval):
    """
    Initialize Arduino with timestamp, personal ID, and wake-up interval
    """
    global arduino_serial
    if not arduino_serial or not arduino_serial.is_open:
        connect_arduino()
    try:
        arduino_serial.write(b"l\n")

        # Wait for Arduino to send a "READY" signal
        while True:
            response = arduino_serial.readline().decode('utf-8').strip()
            if response:
                print(f"Arduino: {response}")
                if "READY_FOR_DATA" in response:
                    break

        # Send data packet
        packet = f"<{epoch_time},{personal_id},{wakeup_interval}>"
        print(f"[INFO] Sending packet: {packet}")
        arduino_serial.write((packet + '\n').encode('utf-8'))
        arduino_serial.flush()

        # Wait for confirmation from Arduino
        while True:
            response = arduino_serial.readline().decode('utf-8').strip()
            if response:
                print(f"Arduino: {response}")
                if "[INFO] Data received and logging started." in response:
                    print("[INFO] Setup complete. Exiting.")
                    break
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred: {e}")

def download_file(file_path="data_log.csv"):
    """
    Download the Flash-stored data from Arduino as a CSV file
    """
    if not arduino_serial:
        print("[ERROR] Arduino not connected.")
        return
    try:
        arduino_serial.write(b"r\n")
        print("[INFO] Retrieving data from Arduino...")
        with open(file_path, "w") as csv_file:
            csv_file.write("Datetime,Temperature\n")  # Write CSV header
            
            initial_timestamp = None
            wakeup_interval = 300
            personal_id = None

            while True:
                line = arduino_serial.readline().decode('utf-8').strip()
                if not line:
                    continue
                if line == "End of data.":
                    print("Data retrieval complete.")
                    break
                if "Initial Timestamp" in line:
                    _, timestamp = line.split(":")
                    initial_timestamp = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
                elif "Wake-up Interval" in line:
                    _, interval = line.split(":")
                    wakeup_interval = int(interval)
                elif "Personal ID" in line:
                    _, personal_id = line.split(":")
                    csv_file.write(f"ID: {personal_id}\n")
                try:
                    index, temperature = line.split(",")
                    index = int(index)
                    timestamp = (initial_timestamp + timedelta(seconds=(index*int(wakeup_interval)))).strftime("%Y-%m-%d %H:%M:%S")
                    # Write formatted data to the CSV
                    csv_file.write(f"{timestamp},{temperature}\n")
                    print(f"{timestamp},{temperature}")  # Print to console
                except ValueError:
                    print(f"Failed to parse line: {line}")
                    continue
    except Exception as e:
        print(f"Failed to retrieve data: {e}")