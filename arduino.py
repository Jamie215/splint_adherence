# Import libraries
import time
from datetime import datetime, timezone, timedelta
import serial
from serial.tools import list_ports
import sys

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

def connect_arduino(port=search_for_arduino(), baud_rate=115200):
    """
    Establish a serial connection with the Arduino.
    """
    arduino_port = find_arduino_port()
    try:
        arduino_serial = serial.Serial(arduino_port, baud_rate, timeout=2)
        time.sleep(2)
        print("[INFO] Arduino connected.")
    except Exception as e:
        print(f"[ERROR] Failed to connect to Arduino: {e}")

def disconnect_arduino():
    """
    Disconnect Arduino
    """
    global arduino_serial
    if arduino_serial:
        arduino_serial.close()
        arduino_serial = None
        print("Arduino disconnected successfully")

def configure_arduino(personal_):
    """
    Configure Arduino
    """
    arduino_port = find_arduino_port()
    try:
        # Open the serial connection
        with serial.Serial(arduino_port, baud_rate, timeout=2) as ser:
            time.sleep(2)
            ser.write(b"l\n")

            # Wait for Arduino to send a "READY" signal
            while True:
                response = ser.readline().decode('utf-8').strip()
                if response:
                    print(f"Arduino: {response}")
                    if "READY_FOR_DATA" in response:
                        break

            now = datetime.now()
            formatted_time = now.strftime("%y%m%d %H:%M")

            personal_id = input("Enter Personal ID: ").strip()
            print("Select wake-up interval (in seconds):")
            print("1. 5 minutes (300 seconds)")
            print("2. 10 minutes (600 seconds)")
            print("3. 30 minutes (1800 seconds)")
            print("4. 1 hour (3600 seconds)")
            interval_choice = input("Choose (1-4): ").strip()
            interval_options = {"1": "300", "2": "600", "3": "1800", "4": "3600"}
            wakeup_interval = interval_options.get(interval_choice, "300")

            # Send all data in one packet
            packet = f"<{formatted_time},{personal_id},{wakeup_interval}>"
            print(f"Sending packet: {packet}")
            time.sleep(0.5)
            ser.write((packet + '\n').encode('utf-8'))
            ser.flush()

            # Wait for confirmation from Arduino
            while True:
                response = ser.readline().decode('utf-8').strip()
                if response:
                    print(f"Arduino: {response}")
                    if "[INFO] Data received and logging started." in response:
                        print("Setup complete. Exiting.")
                        break
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

def download_file(file_path):
    """
    Download the Flash-stored data from Arduino
    """
    port = find_arduino_port()
    try:
        with serial.Serial(port, baud_rate, timeout=2) as ser:
            ser.write(b"r\n")
            print("Retrieving data from Arduino...")
            with open(file_path, "wb") as csv_file:
                csv_file.write("Datetime,Temperature\n")  # Write CSV header
                initial_timestamp = None
                while True:
                    line = ser.readline().decode('utf-8').strip()
                    if line == "End of data.":
                        print("Data retrieval complete.")
                        break
                    if "Initial Timestamp" in line:
                        _, timestamp = line.split(":")
                        initial_timestamp = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
                    if "Wake-up Interval" in line:
                        _, wakeup_interval = line.split(":")
                    if "Personal ID" in line:
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