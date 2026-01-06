#include <Wire.h>
#include <FlashIAP.h>
#include <Arduino_APDS9960.h>
#include "HS300x.h"

using namespace mbed;

// Flash storage parameters
#define FLASH_PAGE_SIZE          4096
#define CONFIG_ADDRESS           0x70000
#define DATA_START_ADDRESS       0x80000
#define MAX_DATA_ENTRIES         15000
#define END_DATA_MARKER "END_DATA"

// Operation modes
enum OperationMode {
    MODE_IDLE = 0,
    MODE_LOGGING = 1,
};

// Data structures
struct ConfigData {
    uint32_t initialTimestamp;   // UNIX timestamp for data start
    uint32_t wakeupInterval;     // Seconds between readings
    char personalId[16];         // User identifier
    OperationMode mode;          // Current operation mode
};

struct InitializationData {
    uint32_t timestamp;
    uint32_t wakeupInterval;
    char personalId[16];
    uint32_t checksum;
};

struct TemperatureData {
    uint32_t elapsedSeconds;     // Actual elapsed time since start (not index * interval)
    float temperature;
    uint8_t proximityVal;        // Now unsigned to store 0-255 range
};

// Configuration data
ConfigData config = {
    0,
    0,
    "DEFAULT_ID",
    MODE_IDLE,
};

uint32_t currentIndex = 0;
uint32_t startMillis = 0;       // Track when logging started
OperationMode currentMode = MODE_IDLE;
FlashIAP flash;

#define SERIAL_BAUD_RATE 9600

// Function declarations
bool saveConfig();
bool saveTemperatureReading(float temperature, uint8_t proximityVal, uint32_t elapsedSeconds);
bool initializeDevice(const uint8_t* packedData);
uint32_t findHighestDataIndex();
void sendReadableData();
void processSerialCommand();

bool saveConfig() {
    int result = flash.erase(CONFIG_ADDRESS, FLASH_PAGE_SIZE);
    if (result != 0) return false;
    
    result = flash.program(&config, CONFIG_ADDRESS, sizeof(ConfigData));
    if (result != 0) return false;

    ConfigData verifyConfig;
    if (flash.read(&verifyConfig, CONFIG_ADDRESS, sizeof(ConfigData)) != 0 ||
        memcmp(&config, &verifyConfig, sizeof(ConfigData)) != 0) {
        return false;
    }
    
    return true;
}

bool saveTemperatureReading(float temperature, uint8_t proximityVal, uint32_t elapsedSeconds) {
    uint32_t dataOffset = currentIndex * sizeof(TemperatureData);
    uint32_t dataAddress = DATA_START_ADDRESS + dataOffset;
    
    if (dataAddress < flash.get_flash_start() || 
        dataAddress + sizeof(TemperatureData) > flash.get_flash_start() + flash.get_flash_size()) {
        return false;
    }
    
    TemperatureData data;
    data.elapsedSeconds = elapsedSeconds;  // Store actual elapsed time
    data.temperature = temperature;
    data.proximityVal = proximityVal;
    
    int writeResult = flash.program(&data, dataAddress, sizeof(TemperatureData));
    if (writeResult != 0) return false;
    
    currentIndex++;
    return true;
}

bool initializeDevice(const uint8_t* packedData) {
    InitializationData initData;
    memcpy(&initData, packedData, sizeof(InitializationData));

    uint32_t calculatedChecksum = 0;
    const uint8_t* dataPtr = packedData;
    for (size_t i = 0; i < (sizeof(InitializationData) - sizeof(uint32_t)); ++i) {
        calculatedChecksum += dataPtr[i];
    }
    calculatedChecksum &= 0xFFFFFFFF;
    
    if (calculatedChecksum != initData.checksum) {
        Serial.println("CHECKSUM_ERROR");
        return false;
    }

    uint32_t totalDataBytes = MAX_DATA_ENTRIES * sizeof(TemperatureData);
    uint32_t pagesNeeded = (totalDataBytes + FLASH_PAGE_SIZE - 1) / FLASH_PAGE_SIZE;
    
    for (uint32_t page = 0; page < pagesNeeded; page++) {
        uint32_t pageAddress = DATA_START_ADDRESS + (page * FLASH_PAGE_SIZE);
        int result = flash.erase(pageAddress, FLASH_PAGE_SIZE);
        if (result != 0) {
            Serial.print("ERROR: Failed to erase data page at 0x");
            Serial.println(pageAddress, HEX);
            return false;
        }
    }

    config.initialTimestamp = initData.timestamp;
    config.wakeupInterval = initData.wakeupInterval;
    
    memset(config.personalId, 0, sizeof(config.personalId));
    strncpy(config.personalId, initData.personalId, sizeof(config.personalId) - 1);
    config.personalId[sizeof(config.personalId) - 1] = '\0';
    
    currentIndex = 0;
    config.mode = MODE_IDLE;
    
    return saveConfig();
}

uint32_t findHighestDataIndex() {
    uint32_t highestIndex = 0;
    TemperatureData data;
    
    for (uint32_t i = 0; i < MAX_DATA_ENTRIES; i++) {
        uint32_t dataAddress = DATA_START_ADDRESS + (i * sizeof(TemperatureData));
        
        if (flash.read(&data, dataAddress, sizeof(TemperatureData)) == 0) {
            if (data.temperature > -100 && data.temperature < 200) {
                highestIndex = i + 1;
            }
        } else {
            break;
        }
    }
    return highestIndex;
}

void sendReadableData() {
    Serial.print("Initial Timestamp,");
    Serial.println(config.initialTimestamp);
    
    Serial.print("Wake-up Interval (Seconds),");
    Serial.println(config.wakeupInterval);
    
    Serial.print("Personal ID,");
    Serial.println(config.personalId);
    
    // Header indicates elapsed seconds
    Serial.println("Timestamp,Temperature,ProximityVal");
    
    TemperatureData data;
    uint32_t numEntries = findHighestDataIndex();
    
    for (uint32_t i = 0; i < numEntries; i++) {
        uint32_t dataAddress = DATA_START_ADDRESS + i * sizeof(TemperatureData);
        
        if (flash.read(&data, dataAddress, sizeof(TemperatureData)) != 0) {
            Serial.print("ERROR,");
            Serial.println(i);
            continue;
        }
        
        // Calculate actual timestamp from elapsed seconds
        uint32_t timestamp = config.initialTimestamp + data.elapsedSeconds;
        
        Serial.print(timestamp);
        Serial.print(",");
        Serial.print(data.temperature, 2);
        Serial.print(",");
        Serial.println(data.proximityVal);
        delay(5);
    }
    
    Serial.println(END_DATA_MARKER);
}

void processSerialCommand() {
    if (Serial.available()) {
        char cmd = Serial.read();
        
        switch (cmd) {
            case '?':
                Serial.println("Hello World!");
                break;
            case '!':
                if (findHighestDataIndex() > 0) {
                    Serial.println("HAS_DATA");
                } else {
                    Serial.println("NEED_CONFIGURATION");
                }
                break;
            case 'i':
                {
                    const size_t dataSize = sizeof(InitializationData);
                    uint8_t packedData[dataSize];

                    Serial.println("READY_FOR_INIT");

                    unsigned long startTime = millis();
                    int bytesRead = 0;
        
                    while (bytesRead < dataSize) {
                        if (millis() - startTime > 5000) {
                            Serial.println("TIMEOUT");
                            return;
                        }
                        
                        if (Serial.available()) {
                            packedData[bytesRead++] = (uint8_t)Serial.read();
                        } else {
                            delay(10);
                        }
                    }

                    if (initializeDevice(packedData)) {                        
                        Serial.println("INITIALIZED");
                        delay(100);
                        digitalWrite(LED_PWR, LOW);
                        digitalWrite(LEDR, HIGH);
                        digitalWrite(LEDG, HIGH);
                        digitalWrite(LEDB, HIGH);
                        NRF_POWER->SYSTEMOFF = 1;
                    } else {
                        Serial.println("INIT_FAILED");
                    }
                }
                break;
            case 'r':
                sendReadableData();
                break;
            default:
                Serial.println("UNKNOWN");
                break;
        }
    }
}

void setup() {
    Serial.begin(SERIAL_BAUD_RATE);

    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);

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

    if (flash.init() != 0) {
        currentMode = MODE_IDLE;
        saveConfig();
        Serial.println("Flash initialization failed");
        return;
    }
    
    flash.read(&config, CONFIG_ADDRESS, sizeof(ConfigData));
    currentIndex = findHighestDataIndex();
    
    // Mode transitions
    if (config.mode == MODE_IDLE && currentIndex == 0) {
        config.mode = MODE_LOGGING;
        saveConfig();

        // Power saving configurations
        NRF_USBD->ENABLE = 0;
        NRF_CLOCK->TASKS_HFCLKSTOP = 1;
        NRF_SAADC->ENABLE = 0;
        NRF_PWM0->ENABLE = 0;
        NRF_PWM1->ENABLE = 0;
        NRF_PWM2->ENABLE = 0;
        NRF_PDM->ENABLE = 0;
        NRF_I2S->ENABLE = 0;
        NRF_SPI0->ENABLE = 0;
        NRF_SPI1->ENABLE = 0;
        NRF_UART0->TASKS_STOPTX = 1;
        NRF_UART0->TASKS_STOPRX = 1;
        NRF_UART0->ENABLE = 0;
        NRF_UARTE1->TASKS_STOPTX = 1;
        NRF_UARTE1->TASKS_STOPRX = 1;
        NRF_UARTE1->ENABLE = 0;
        NRF_RADIO->POWER = 0; 
        NRF_QDEC->ENABLE = 0;
        NRF_COMP->ENABLE = 0;
        NRF_POWER->DCDCEN = 1;

        *(volatile uint32_t *)0x40002FFC = 0;
        *(volatile uint32_t *)0x40002FFC;
        *(volatile uint32_t *)0x40002FFC = 1;

        digitalWrite(LEDR, HIGH);
        digitalWrite(LEDG, HIGH);
        digitalWrite(LEDB, HIGH);
        
        // FIXED: Record start time for accurate timing
        startMillis = millis();
        
    } else if (config.mode == MODE_LOGGING) {
        config.mode = MODE_IDLE;
        saveConfig();

        NRF_USBD->ENABLE = 1;
        NRF_CLOCK->TASKS_HFCLKSTART = 1;
        NRF_UART0->ENABLE = 1;
        NRF_UARTE1->ENABLE = 1;
    }
    
    currentMode = config.mode;
    
    if (currentMode == MODE_IDLE) {        
        digitalWrite(LEDR, HIGH);
        digitalWrite(LEDG, LOW);
        digitalWrite(LEDB, HIGH);
        Serial.println("Ready for Connection");
    } else {
        Serial.end();
        startMillis = millis();  // Initialize timing reference
    }
}

void loop() {
    switch (currentMode) {
        case MODE_LOGGING: {
            // Calculate target wake time BEFORE doing any work
            static uint32_t nextWakeTime = 0;
            if (nextWakeTime == 0) {
                nextWakeTime = millis();  // Initialize on first run
            }
            
            // Calculate actual elapsed seconds since logging started
            uint32_t elapsedSeconds = (millis() - startMillis) / 1000;
            
            // Initialize sensors
            APDS.begin();
            HS300x.begin();
            delay(50);

            // Wait for proximity sensor
            while (!APDS.proximityAvailable()) {}

            // Read sensors
            int rawProximity = APDS.readProximity();
            uint8_t proximityVal = (uint8_t)(rawProximity & 0xFF);  // Ensure 0-255 range
            float temperature = HS300x.readTemperature();

            // Save reading with actual elapsed time
            if (!saveTemperatureReading(temperature, proximityVal, elapsedSeconds)) {
                currentMode = MODE_IDLE;
                config.mode = MODE_IDLE;
                saveConfig();
                return;
            }
            
            // Turn off sensors
            APDS.end();
            HS300x.end();
            digitalWrite(LED_PWR, LOW);
            
            // Calculate next wake time based on interval, not current time
            nextWakeTime += config.wakeupInterval * 1000UL;
            
            // Calculate how long to sleep (accounting for work already done)
            uint32_t currentTime = millis();
            if (nextWakeTime > currentTime) {
                uint32_t sleepDuration = nextWakeTime - currentTime;
                delay(sleepDuration);
            }
            
            break;
        }
        case MODE_IDLE:
        default: {
            processSerialCommand();
            delay(100);
            break;
        }
    }
}