#include "mbed.h"
#include "rtos.h"
#include "Wire.h"
#include "nrf.h"
#include "USBSerial.h"
#include "HS300x.h"
#include "FlashIAP.h"

using namespace mbed;
using namespace rtos;

#define DEFAULT_WAKEUP_INTERVAL 300 // Default 5 minutes (in seconds)

// Flash storage parameters
#define FLASH_PAGE_SIZE          4096  // 4KB pages on nRF52840
#define CONFIG_ADDRESS           0x70000
#define DATA_START_ADDRESS       0x80000
#define MAX_DATA_ENTRIES         15000
#define END_DATA_MARKER "END_DATA"

// Simplified operation modes - only these two core states
enum OperationMode {
    MODE_IDLE = 0,       // Default mode, waits for commands/initialization
    MODE_LOGGING = 1,    // Collecting temperature data
};

// Data structures
struct ConfigData {
    uint32_t initialTimestamp;  // UNIX timestamp for data start
    uint32_t wakeupInterval;    // Seconds between readings
    char personalId[16];        // User identifier
    OperationMode mode;         // Current operation mode
};

struct InitializationData {
    uint32_t timestamp;
    uint32_t wakeupInterval;
    char personalId[16];
    uint32_t checksum;
};

struct TemperatureData {
    uint32_t index;
    float temperature;
};

// Configuration data with defaults
ConfigData config = {
    0,                       // initialTimestamp - 0 means not initialized
    DEFAULT_WAKEUP_INTERVAL, // wakeupInterval
    "DEFAULT_ID",            // personalId
    MODE_IDLE,               // mode - default to command mode
};

uint32_t currentIndex = 0;

// Current operation mode
OperationMode currentMode = MODE_IDLE;

// Flash access object
FlashIAP flash;

// Serial communication-related
USBSerial* serialPtr = nullptr;

// Function to get serial interface when needed
USBSerial& getSerial() {
    if (serialPtr == nullptr) {
        // Only create the USBSerial object when first needed
        serialPtr = new USBSerial();
        
        // Give hardware time to initialize
        ThisThread::sleep_for(100); 
    }
    return *serialPtr;
}

// Function to release serial interface
void releaseSerial() {
    if (serialPtr != nullptr) {
        delete serialPtr;
        serialPtr = nullptr;
        
        // Explicitly disable hardware
        NRF_USBD->ENABLE = 0;
    }
}

// Function to save configuration to flash
bool saveConfig() {
    // Erase config page
    int result = flash.erase(CONFIG_ADDRESS, FLASH_PAGE_SIZE);
    if (result != 0) {
        return false;
    }
    
    // Program config data
    result = flash.program(&config, CONFIG_ADDRESS, sizeof(ConfigData));
    ThisThread::sleep_for(100);
    if (result != 0) {
        return false;
    }

    // Verify written data
    ConfigData verifyConfig;
    if (flash.read(&verifyConfig, CONFIG_ADDRESS, sizeof(ConfigData)) != 0 ||
        memcmp(&config, &verifyConfig, sizeof(ConfigData)) != 0) {
        return false;
    }
    
    return true;
}

// Function to save temperature reading to flash
bool saveTemperatureReading(float temperature) {
    uint32_t dataOffset = currentIndex * sizeof(TemperatureData);
    uint32_t dataAddress = DATA_START_ADDRESS + dataOffset;
    
    // Sanity check the address is within valid flash range
    if (dataAddress < flash.get_flash_start() || 
        dataAddress + sizeof(TemperatureData) > flash.get_flash_start() + flash.get_flash_size()) {
        return false;
    }
    
    // Prepare temperature data
    TemperatureData data;
    data.index = currentIndex;
    data.temperature = temperature;
    
    // Write to flash with detailed error reporting
    int writeResult = flash.program(&data, dataAddress, sizeof(TemperatureData));
    ThisThread::sleep_for(100);
    if (writeResult != 0) {
        return false;
    }
        
    // Update data index
    currentIndex++;
    
    return true;
}

// Function to initialize device with parameters from packed data
bool initializeDevice(const uint8_t* packedData) {
    InitializationData initData;
    USBSerial& serial = getSerial();

    // Copy the packed data into our structure
    memcpy(&initData, packedData, sizeof(InitializationData));

    // Verify checksum
    uint32_t calculatedChecksum = 0;
    const uint8_t* dataPtr = packedData;

    // Sum all bytes except the last 4 bytes (which are the checksum)
    for (size_t i = 0; i < (sizeof(InitializationData) - sizeof(uint32_t)); ++i) {
        calculatedChecksum += dataPtr[i];
    }
    calculatedChecksum &= 0xFFFFFFFF;
    
    if (calculatedChecksum != initData.checksum) {
        serial.printf("CHECKSUM_ERROR\r\n");
        return false;
    }

    // Calculate how many pages we need to erase based on MAX_DATA_ENTRIES
    uint32_t totalDataBytes = MAX_DATA_ENTRIES * sizeof(TemperatureData);
    uint32_t pagesNeeded = (totalDataBytes + FLASH_PAGE_SIZE - 1) / FLASH_PAGE_SIZE; // Ceiling division
    
    // Erase all data pages
    for (uint32_t page = 0; page < pagesNeeded; page++) {
        uint32_t pageAddress = DATA_START_ADDRESS + (page * FLASH_PAGE_SIZE);
        int result = flash.erase(pageAddress, FLASH_PAGE_SIZE);
        if (result != 0) {
            serial.printf("ERROR: Failed to erase data page at 0x%08X\r\n", pageAddress);
            return false;
        }
    }

    // Copy the initialization data to our config
    config.initialTimestamp = initData.timestamp;
    config.wakeupInterval = initData.wakeupInterval;
    
    // Safely copy personal ID with explicit null termination
    memset(config.personalId, 0, sizeof(config.personalId));  // Zero out first
    strncpy(config.personalId, initData.personalId, sizeof(config.personalId) - 1);
    config.personalId[sizeof(config.personalId) - 1] = '\0';  // Ensure null termination
    
    currentIndex = 0;
    config.mode = MODE_IDLE;
    
    return saveConfig();
}

// Function to optimize power for low power mode
void optimizePower() {
    // Only disable communication in logging mode
    if (currentMode == MODE_LOGGING) {
        NRF_USBD->ENABLE = 0;
    }
    
    // Disable unused analog peripherals
    NRF_SAADC->ENABLE = 0;
    NRF_PWM0->ENABLE = 0;
    NRF_PWM1->ENABLE = 0;
    NRF_PWM2->ENABLE = 0;
    NRF_PDM->ENABLE = 0;
    NRF_I2S->ENABLE = 0;

    // Stop high-frequency clock, but keep low-frequency clock for WDT
    NRF_CLOCK->EVENTS_HFCLKSTARTED = 0;
    NRF_CLOCK->TASKS_HFCLKSTOP = 1;

    // Disable unused peripherals
    NRF_TWI0->ENABLE = 0;
    
    // Disable SPI module
    NRF_SPI0->ENABLE = 0;
    NRF_SPI1->ENABLE = 0;

    // Disable UART/UARTE
    NRF_UART0->TASKS_STOPTX = 1;
    NRF_UART0->TASKS_STOPRX = 1;
    NRF_UARTE0->TASKS_STOPTX = 1;
    NRF_UARTE0->TASKS_STOPRX = 1;
    NRF_UARTE0->ENABLE = 0;

    // Disable radio (BLE)
    NRF_RADIO->POWER = 0; 

    // Disable other peripherals
    NRF_QDEC->ENABLE = 0;
    NRF_COMP->ENABLE = 0;
    NRF_TEMP->TASKS_STOP = 1;
    
    // Enable DCDC converter for power efficiency
    NRF_POWER->DCDCEN = 1;
}

// Modified enterSleep function that uses watchdog for timing
void enterSleep() {
    // Only enter sleep in logging mode
    if (currentMode != MODE_LOGGING) return;
    
    // End I2C communication
    Wire1.end();
    
    // Power off sensors
    HS300x.end();
    digitalWrite(P0_22, LOW);
    digitalWrite(P1_0, LOW);

    digitalWrite(PIN_ENABLE_SENSORS_3V3, LOW);
    digitalWrite(PIN_ENABLE_I2C_PULLUP, LOW);
    
    optimizePower();

    delay(config.wakeupInterval * 1000);

    // Reset pins for sensor power
    digitalWrite(P0_22, HIGH);
    digitalWrite(P1_0, HIGH);
    
    // Re-enable sensors and I2C pullups for next reading
    digitalWrite(PIN_ENABLE_SENSORS_3V3, HIGH);
    digitalWrite(PIN_ENABLE_I2C_PULLUP, HIGH);
    
    // Re-initialize I2C
    Wire1.begin();
    Wire1.setClock(100000);
    
    // Re-initialize the sensor
    HS300x.begin();
    ThisThread::sleep_for(10);
}

// Function to scan flash and find the highest used data index
uint32_t findHighestDataIndex() {
    uint32_t highestIndex = 0;
    TemperatureData data;
    
    for (uint32_t i = 0; i < MAX_DATA_ENTRIES; i++) {
        uint32_t dataAddress = DATA_START_ADDRESS + (i * sizeof(TemperatureData));
        
        if (flash.read(&data, dataAddress, sizeof(TemperatureData)) == 0) {
            // Check if this is valid data (some simple validation)
            if (data.temperature > -100 && data.temperature < 200) {
                // Valid temperature range, this slot is likely used
                if (data.index >= highestIndex) {
                    highestIndex = data.index + 1;
                }
            }
        } else {
            break; // Error reading, probably hit unused flash
        }
    }
    return highestIndex;
}

// Function to send data in readable format(CSV)
void sendReadableData() {
    USBSerial& serial = getSerial();
    
    // Send metadata first
    serial.printf("Initial Timestamp,%lu\r\n", config.initialTimestamp);
    serial.printf("Wake-up Interval (Seconds),%lu\r\n", config.wakeupInterval);
    serial.printf("Personal ID,%s\r\n", config.personalId);
    
    // Send column headers
    serial.printf("Timestamp,Temperature\r\n");
    
    // Read and send data entries
    TemperatureData data;
    uint32_t numEntries = findHighestDataIndex();
    
    for (uint32_t i = 0; i < numEntries; i++) {
        uint32_t dataAddress = DATA_START_ADDRESS + i * sizeof(TemperatureData);
        
        // Read data from flash
        if (flash.read(&data, dataAddress, sizeof(TemperatureData)) != 0) {
            serial.printf("ERROR,%lu\r\n", i);
            continue;
        }
        
        // Calculate timestamp
        uint32_t timestamp = config.initialTimestamp + (data.index * config.wakeupInterval);
        
        // Send data point
        serial.printf("%lu,%.2f\r\n", timestamp, data.temperature);
        ThisThread::sleep_for(5); // Small delay to prevent overrun
    }
    
    // Send end marker
    serial.printf(END_DATA_MARKER);
}

// Function to process incoming serial command
void processSerialCommand() {
    USBSerial& serial = getSerial();
    if (serial.available()) {
        char cmd = serial.getc();
        
        switch (cmd) {
            case '?': // Handshake request
                serial.printf("Hello World!\r\n");
                break;
            case '!': // Status request
                {
                    if (findHighestDataIndex() > 0) {
                        serial.printf("HAS_DATA\r\n");
                    } else {
                        serial.printf("NEED_CONFIGURATION\r\n");
                    }
                }
                break;
            case 'i': // Initialize with binary timestamp
                {
                    // Size of the packed initialization data
                    const size_t dataSize = sizeof(InitializationData);
                    uint8_t packedData[dataSize];

                    serial.printf("READY_FOR_INIT\r\n");

                    unsigned long startTime = millis();
                    int bytesRead = 0;
        
                    while (bytesRead < dataSize) {
                        if (millis() - startTime > 5000) {
                            serial.printf("TIMEOUT\r\n");
                            return;
                        }
                        
                        if (serial.available()) {
                            packedData[bytesRead++] = (uint8_t)serial.getc();
                        } else {
                            ThisThread::sleep_for(10);
                        }
                    }

                    // Initialize the device with the packed data
                    if (initializeDevice(packedData)) {                        
                        // Send initialization confirmation
                        serial.printf("INITIALIZED\r\n");
                        ThisThread::sleep_for(1000);
                        digitalWrite(LED_PWR, LOW);
                        NRF_POWER->SYSTEMOFF = 1;
                    } else {
                        serial.printf("INIT_FAILED\r\n");
                    }
                }
                break;
            case 'r': // Send data in readable format
                sendReadableData();
                break;
            default:
                // Unknown command
                serial.printf("UNKNOWN\r\n");
                break;
        }
    }
}

// Updated setup function to handle watchdog resets
void setup() {
    // Set & Disable LED_BUILTIN
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);

    // Set LED_PWR
    pinMode(LED_PWR, OUTPUT);
    digitalWrite(LED_PWR, HIGH);
    
    #ifdef LEDR
    pinMode(LEDR, OUTPUT);
    digitalWrite(LEDR, HIGH);
    #endif
    
    #ifdef LEDG
    pinMode(LEDG, OUTPUT);
    digitalWrite(LEDG, HIGH);
    #endif
    
    #ifdef LEDB
    pinMode(LEDB, OUTPUT);
    digitalWrite(LEDB, HIGH);
    #endif

    // Initialize flash and load configuration
    if (flash.init() != 0) {
        currentMode = MODE_IDLE;  // Default to command mode on error
        saveConfig();
        return;
    }
    
    // Load configuration
    flash.read(&config, CONFIG_ADDRESS, sizeof(ConfigData));
    
    // Find current index for data storage
    currentIndex = findHighestDataIndex();
    
    // Mode Switch Case: IDLE to LOGGING
    if (config.mode == MODE_IDLE && currentIndex == 0) {
        config.mode = MODE_LOGGING;
        saveConfig();
    } else if (config.mode == MODE_LOGGING) { // Mode Switch Case: LOGGING to IDLE
        config.mode = MODE_IDLE;
        saveConfig();
    }
    
    // Set current mode from config
    currentMode = config.mode;

    // Initialize sensor power pins
    pinMode(P0_22, OUTPUT);
    digitalWrite(P0_22, HIGH);
    
    pinMode(P1_0, OUTPUT);
    digitalWrite(P1_0, HIGH);
    ThisThread::sleep_for(10);

    // Set up I2C pins
    pinMode(P0_14, INPUT_PULLUP);
    pinMode(P0_15, INPUT_PULLUP);

    // Initialize I2C
    Wire1.begin();
    Wire1.setClock(100000);

    // Configure sensor power pins according to the optimization
    pinMode(PIN_ENABLE_SENSORS_3V3, OUTPUT);
    pinMode(PIN_ENABLE_I2C_PULLUP, OUTPUT);
    digitalWrite(PIN_ENABLE_SENSORS_3V3, HIGH);
    digitalWrite(PIN_ENABLE_I2C_PULLUP, HIGH);
    
    // Initialize temperature sensor
    HS300x.begin();
    ThisThread::sleep_for(500);

    struct FlashGuard {
        ~FlashGuard() { flash.deinit(); }
    } flash_guard;
}

int main() {
    setup();
    
    // Keep serial interface if we're not in logging mode
    if (currentMode == MODE_IDLE) {
        getSerial();
    } else {
        releaseSerial();
    }

    while (true) {
        switch (currentMode) {
            case MODE_LOGGING: {
                digitalWrite(LED_PWR, HIGH);
                float temperature = HS300x.readTemperature();
                digitalWrite(LED_PWR, LOW);

                // Save reading to flash
                if (!saveTemperatureReading(temperature)) {
                    // Error saving, switch to idle mode
                    currentMode = MODE_IDLE;
                    config.mode = MODE_IDLE;
                    saveConfig();
                    continue;
                }
                
                // Go to sleep
                enterSleep();
                break;
            }
            case MODE_IDLE:
            default: {
                processSerialCommand();
                ThisThread::sleep_for(100);
                break;
            }
        }
    }
}