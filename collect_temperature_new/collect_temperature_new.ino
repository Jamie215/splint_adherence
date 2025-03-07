#include "mbed.h"
#include "rtos.h"
#include "Wire.h"
#include "nrf.h"
#include "USBSerial.h"
#include "HS300x.h"
#include "FlashIAP.h"

using namespace mbed;
using namespace rtos;

#define DEBUG_GPIO_PIN NRF_GPIO_PIN_MAP(1, 9)
#define DEFAULT_WAKEUP_INTERVAL 300 // Default 5 minutes (in seconds)

// Flash storage parameters
#define FLASH_PAGE_SIZE          4096  // 4KB pages on nRF52840
#define CONFIG_ADDRESS           0x80000
#define DATA_START_ADDRESS       0x81000
#define MAX_DATA_ENTRIES         1000

// Command and response prefixes
#define CMD_PREFIX "CMD:"
#define RESP_PREFIX "RESP:"
#define DATA_PREFIX "DATA:"

// Command types
#define CMD_STATUS "STATUS"
#define CMD_INIT "INIT"
#define CMD_RETRIEVE "RETRIEVE"

// Response types
#define RESP_OK "OK"
#define RESP_ERROR "ERROR"
#define DATA_BEGIN "BEGIN"
#define DATA_END "END"

// Maximum buffer size for commands
#define MAX_BUFFER_SIZE 128

// Simplified operation modes - only these three core states
enum OperationMode {
    MODE_IDLE = 0,       // Default mode, waits for commands/initialization
    MODE_LOGGING = 1,       // Collecting temperature data
    MODE_DATA_RETRIEVAL = 2 // Retrieving collected data
};

// Data structures
struct ConfigData {
    uint32_t initialTimestamp;  // UNIX timestamp for data start
    uint32_t wakeupInterval;    // Seconds between readings
    char personalId[16];        // User identifier
    uint32_t currentDataIndex;  // Number of readings collected
    OperationMode mode;         // Current operation mode
    uint32_t magicNumber;       // For validation (0xABCD1234)
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
    0,                       // currentDataIndex
    MODE_IDLE,            // mode - default to command mode
    0xABCD1234               // magicNumber for validation
};

// Current operation mode
OperationMode currentMode = MODE_IDLE;

// Timer for wake-up
LowPowerTimeout wakeupTimer;
volatile bool wakeupFlag = false;

// Serial command buffer
char cmdBuffer[MAX_BUFFER_SIZE];
int cmdIndex = 0;

// Flash access object
FlashIAP flash;

// Serial communication
USBSerial serial;

// Callback for timer
void wakeupCallback() {
    wakeupFlag = true;
}

// Save configuration to flash
bool saveConfig() {
    // Sync the configuration
    config.mode = currentMode;
    config.magicNumber = 0xABCD1234;
    
    // Erase config page
    int result = flash.erase(CONFIG_ADDRESS, FLASH_PAGE_SIZE);
    if (result != 0) {
        return false;
    }
    
    // Program config data
    result = flash.program(&config, CONFIG_ADDRESS, sizeof(ConfigData));
    if (result != 0) {
        return false;
    }
    
    return true;
}

void blinkDebugPin(int times, int onTimeMs = 200, int offTimeMs = 200) {
    for (int i = 0; i < times; i++) {
        nrf_gpio_pin_set(DEBUG_GPIO_PIN);
        ThisThread::sleep_for(onTimeMs);
        nrf_gpio_pin_clear(DEBUG_GPIO_PIN);
        if (i < times - 1) {
            ThisThread::sleep_for(offTimeMs);
        }
    }
}

// Save temperature reading to flash
bool saveTemperatureReading(float temperature) {    
    // Calculate address for this reading
    uint32_t dataAddress = DATA_START_ADDRESS + (config.currentDataIndex % MAX_DATA_ENTRIES) * sizeof(TemperatureData);
    
    // If this is the first entry in a page, erase the page first
    if ((config.currentDataIndex % (FLASH_PAGE_SIZE / sizeof(TemperatureData))) == 0) {
        uint32_t pageAddress = dataAddress & ~(FLASH_PAGE_SIZE - 1); // Align to page boundary
        
        if (flash.erase(pageAddress, FLASH_PAGE_SIZE) != 0) {
            blinkDebugPin(10, 50, 50);
            return false;
        }
    }
    
    // Prepare temperature data
    TemperatureData data;
    data.index = config.currentDataIndex;
    data.temperature = temperature;
    
    // Write to flash
    if (flash.program(&data, dataAddress, sizeof(TemperatureData)) != 0) {
        blinkDebugPin(10, 50, 50);
        return false;
    }
    
    // Update data index
    config.currentDataIndex++;
    
    // Save updated config
    return saveConfig();
}

// Parse initialization packet; format: <epoch_time,personal_id,wakeup_interval>
bool initializeDevice(const char* packet) {
    // Make a copy of the packet to modify
    char buffer[64];
    strncpy(buffer, packet, sizeof(buffer) - 1);
    buffer[sizeof(buffer) - 1] = '\0';
    
    // Remove < and > characters if present
    if (buffer[0] == '<') {
        memmove(buffer, buffer + 1, strlen(buffer));
        char* endBracket = strchr(buffer, '>');
        if (endBracket) {
            *endBracket = '\0';
        }
    }
    
    // Parse comma-separated values
    char* token = strtok(buffer, ",");
    if (!token) {
        serial.printf("[ERROR] Missing timestamp\r\n");
        return false;
    }
    config.initialTimestamp = strtoul(token, NULL, 10);
    
    token = strtok(NULL, ",");
    if (!token) {
        serial.printf("[ERROR] Missing personal ID\r\n");
        return false;
    }
    strncpy(config.personalId, token, sizeof(config.personalId) - 1);
    config.personalId[sizeof(config.personalId) - 1] = '\0';
    
    token = strtok(NULL, ",");
    if (!token) {
        serial.printf("[ERROR] Missing wake-up interval\r\n");
        return false;
    }
    config.wakeupInterval = strtoul(token, NULL, 10);
    
    // Reset data index
    config.currentDataIndex = 0;
    
    // Save configuration
    return saveConfig();
}

// Function to send a formatted response
void sendResponse(const char* prefix, const char* type, const char* data = NULL) {
    if (data != NULL) {
        serial.printf("%s%s;%s\r\n", prefix, type, data);
    } else {
        serial.printf("%s%s;\r\n", prefix, type);
    }
}

// Prepare the device for complete shutdown (to begin logging on next power-up)
void prepareForLogging() {
    
    // Send initialization confirmation message
    sendResponse(RESP_PREFIX, RESP_OK, "INITIALIZED");
    ThisThread::sleep_for(1000);

    while(serial.available()) {
        serial.getc(); // Discard any pending input
    }
    
    // Indicate the device is ready for logging
    blinkDebugPin(5, 100, 100);
}

// Power optimization functions
void optimizePower() {
    // Only disable communication in logging mode
    if (currentMode == MODE_LOGGING) {
        NRF_UARTE0->ENABLE = 0;
        NRF_UART0->ENABLE = 0;
        NRF_USBD->ENABLE = 0;
    }
    
    // Stop high-frequency clock
    NRF_CLOCK->TASKS_HFCLKSTOP = 1;
    
    // Disable unused analog peripherals  
    NRF_SAADC->ENABLE = 0;
    NRF_PWM0->ENABLE = 0;
    NRF_PWM1->ENABLE = 0;
    NRF_PWM2->ENABLE = 0;
    
    // Configure SCB for proper deep sleep
    SCB->SCR |= SCB_SCR_SLEEPDEEP_Msk;
    SCB->SCR |= SCB_SCR_SEVONPEND_Msk;
}

void restoreSystem() {
    // Clear sleep deep bit
    SCB->SCR &= ~SCB_SCR_SLEEPDEEP_Msk;
    SCB->SCR &= ~SCB_SCR_SEVONPEND_Msk;
    
    // Re-enable USB and UART when not in logging mode
    if (currentMode != MODE_LOGGING) {
        if (NRF_USBD->ENABLE == 0) {
            NRF_USBD->ENABLE = 1;
        }
        if (NRF_UARTE0->ENABLE == 0) {
            NRF_UARTE0->ENABLE = 1;
        }
    }
}

// Enter sleep mode with wake-up timer
void enterSleep() {
    // Only enter sleep in logging mode
    if (currentMode != MODE_LOGGING) return;
    
    // End I2C communication
    Wire1.end();
    
    // Power off sensors
    digitalWrite(P0_22, LOW);
    digitalWrite(P1_0, LOW);
    
    optimizePower();

    // Set up timer for wake-up
    wakeupFlag = false;    
    config.wakeupInterval = 30; //DEBUG ONLY
    wakeupTimer.attach(&wakeupCallback, config.wakeupInterval); 
    
    // Wait for timer interrupt
    while (!wakeupFlag) {
        __WFI();
    }

    // Restore system after wake-up
    restoreSystem();
    
    // Restore peripherals & sensors for normal operation
    pinMode(P0_14, INPUT_PULLUP);
    pinMode(P0_15, INPUT_PULLUP);
    
    digitalWrite(P0_22, HIGH);
    digitalWrite(P1_0, HIGH);
    ThisThread::sleep_for(10);
    
    // Reinitialize I2C
    Wire1.begin();
    Wire1.setClock(100000);
}

// Function to handle device status request
void handleStatusRequest() {
    // Send appropriate status based on device state
    if (currentMode == MODE_LOGGING) {
        sendResponse(RESP_PREFIX, RESP_OK, "LOGGING");
    } else if (config.currentDataIndex > 0) {
        sendResponse(RESP_PREFIX, RESP_OK, "HAS_DATA");
    } else if (config.initialTimestamp > 0) {
        sendResponse(RESP_PREFIX, RESP_OK, "CONFIGURED");
    } else {
        sendResponse(RESP_PREFIX, RESP_OK, "NOT_CONFIGURED");
    }
}

// Function to handle initialization request
void handleInitRequest() {
    sendResponse(RESP_PREFIX, RESP_OK, "READY_FOR_INIT");
}

// Function to handle data retrieval
void handleRetrieveRequest() {
    // Check if there's data to retrieve
    if (config.currentDataIndex == 0) {
        sendResponse(RESP_PREFIX, RESP_ERROR, "NO_DATA");
        return;
    }
    
    // Set mode to data retrieval
    currentMode = MODE_DATA_RETRIEVAL;
    saveConfig();
    
    sendResponse(RESP_PREFIX, RESP_OK, "SENDING_DATA");
    
    // Send data
    sendDataToHost();
}

// Function to send all data to host
void sendDataToHost() {
    // Send metadata first
    serial.printf("Initial Timestamp:%lu\r\n", config.initialTimestamp);
    serial.printf("Wake-up Interval:%lu\r\n", config.wakeupInterval);
    serial.printf("Personal ID:%s\r\n", config.personalId);
    serial.printf("Total Readings:%lu\r\n", config.currentDataIndex);
    
    // Check if there's data to retrieve
    if (config.currentDataIndex == 0) {
        sendResponse(DATA_PREFIX, DATA_BEGIN);
        serial.printf("No data available.\r\n");
        sendResponse(DATA_PREFIX, DATA_END);
        // Return to command mode after data retrieval
        currentMode = MODE_IDLE;
        saveConfig();
        return;
    }
    
    // Signal data transfer start
    sendResponse(DATA_PREFIX, DATA_BEGIN);
    
    // Read and send data entries
    TemperatureData data;
    uint32_t numEntries = min(config.currentDataIndex, MAX_DATA_ENTRIES);
    
    for (uint32_t i = 0; i < numEntries; i++) {
        uint32_t dataAddress = DATA_START_ADDRESS + i * sizeof(TemperatureData);
        
        // Read data from flash
        if (flash.read(&data, dataAddress, sizeof(TemperatureData)) != 0) {
            serial.printf("ERROR,%lu\r\n", i);
            continue;
        }
        
        // Send data point
        serial.printf("%lu,%.2f\r\n", data.index, data.temperature);
        ThisThread::sleep_for(5); // Small delay to prevent overrun
    }
    
    // Signal data transfer end
    sendResponse(DATA_PREFIX, DATA_END);
    
    // Return to command mode after data retrieval
    currentMode = MODE_IDLE;
    saveConfig();
}

// Process a complete command
void processCommand(char* buffer) {
    // Check for structured command format
    if (strncmp(buffer, CMD_PREFIX, strlen(CMD_PREFIX)) == 0) {
        char* cmdStart = buffer + strlen(CMD_PREFIX);
        char* cmdEnd = strchr(cmdStart, ';');
        
        if (cmdEnd == NULL) {
            sendResponse(RESP_PREFIX, RESP_ERROR, "Invalid command format");
            return;
        }
        
        // Extract command portion
        *cmdEnd = '\0';
        cmdEnd++; // Move to payload start
        
        // Process based on command type
        if (strcmp(cmdStart, CMD_STATUS) == 0) {
            handleStatusRequest();
        }
        else if (strcmp(cmdStart, CMD_INIT) == 0) {
            // Check if this has a payload
            if (*cmdEnd != '\0') {
                if (initializeDevice(cmdEnd)) {
                    ThisThread::sleep_for(500);
                    prepareForLogging();

                    ThisThread::sleep_for(1000);

                    NRF_UARTE0->ENABLE = 0;
                    NRF_UART0->ENABLE = 0;
                    NRF_USBD->ENABLE = 0;
                    ThisThread::sleep_for(100);

                    NRF_POWER->SYSTEMOFF = 1;
                } else {
                    serial.printf("[ERROR] Failed to initialize device\r\n");
                    sendResponse(RESP_PREFIX, RESP_ERROR, "INIT_FAILED");
                }
            } else {
                handleInitRequest();
            }
        }
        else if (strcmp(cmdStart, CMD_RETRIEVE) == 0) {
            handleRetrieveRequest();
        }
        else {
            sendResponse(RESP_PREFIX, RESP_ERROR, "Unknown command");
        }
    } else {
        sendResponse(RESP_PREFIX, RESP_ERROR, "Invalid command format");
    }
}

// Process incoming serial data
void processSerialInput() {
    while (serial.available()) {
        char c = serial.getc();
        
        // Handle end of command
        if (c == '\n' || c == '\r') {
            if (cmdIndex > 0) {
                cmdBuffer[cmdIndex] = '\0';
                processCommand(cmdBuffer);
                cmdIndex = 0; // Reset buffer
            }
        } 
        // Add to buffer if space available
        else if (cmdIndex < MAX_BUFFER_SIZE - 1) {
            cmdBuffer[cmdIndex++] = c;
        }
        // Buffer overflow
        else {
            cmdIndex = 0; // Reset buffer
            sendResponse(RESP_PREFIX, RESP_ERROR, "Command too long");
        }
    }
}

// Check for incoming serial commands for non-logging mode
void checkSerialCommands() {
    if (currentMode != MODE_LOGGING) {
        processSerialInput();
    }
}

void setup() {
    // Configure debug pin
    nrf_gpio_cfg_output(DEBUG_GPIO_PIN);

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
    
    // Initialize temperature sensor
    HS300x.begin();
    ThisThread::sleep_for(500);

    // Initialize flash and load configuration
    if (flash.init() != 0) {
        blinkDebugPin(5, 500, 50);
        currentMode = MODE_IDLE;  // Default to command mode on error
        return;
    }
    
    struct FlashGuard {
        ~FlashGuard() { flash.deinit(); }
    } flash_guard;
    
    // Read configuration from flash
    bool validConfig = false;
    if (flash.read(&config, CONFIG_ADDRESS, sizeof(ConfigData)) == 0) {
        // Valid read from flash
        if (config.magicNumber == 0xABCD1234) {
            validConfig = true;
        }
    }
    
    // Determine the appropriate mode based on device state
    if (validConfig) {
        // Check if this device has been configured for logging
        if (config.initialTimestamp > 0 && 
            strlen(config.personalId) > 0 && 
            strcmp(config.personalId, "DEFAULT_ID") != 0) {
                        
            // If we already have collected data, go to IDLE mode for data retrieval
            if (config.currentDataIndex > 0) {
                currentMode = MODE_IDLE;
            } else {
                currentMode = MODE_LOGGING;
            }
        } else {
            // Not fully configured yet, stay in IDLE
            currentMode = MODE_IDLE;
        }
    } else {
        // No valid config, default to command mode
        currentMode = MODE_IDLE;
    }

    config.mode = currentMode;
    saveConfig();
}

int main() {
    setup();

    while (true) {
        // Handle each mode differently
        switch (currentMode) {
            case MODE_LOGGING: {
                // In logging mode, collect temperature readings with deep sleep between
                nrf_gpio_pin_clear(DEBUG_GPIO_PIN);
                
                // Enter low power mode until timer expires
                enterSleep();
                
                // Briefly indicate activity
                nrf_gpio_pin_set(DEBUG_GPIO_PIN);
                
                // Read temperature and save it
                float temperature = HS300x.readTemperature();
                saveTemperatureReading(temperature);
                
                // Turn off the debug pin again
                nrf_gpio_pin_clear(DEBUG_GPIO_PIN);
                break;
            }
            case MODE_DATA_RETRIEVAL: {
                // In data retrieval mode, handle retrieval commands
                sendDataToHost();
                break;
            }
            case MODE_IDLE:
            default: {
                // In command mode, check for commands and sleep briefly
                checkSerialCommands();
                ThisThread::sleep_for(100);
                break;
            }
        }
    }
}