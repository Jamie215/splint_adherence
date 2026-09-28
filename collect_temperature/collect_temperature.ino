#include <stddef.h>
#include <Wire.h>
#include <FlashIAP.h>
#include <Arduino_APDS9960.h>
#include "HS300x.h"

using namespace mbed;

// Flash storage parameters
#define FLASH_PAGE_SIZE          4096
// The config is kept in two flash pages (A/B). Each save goes to the page NOT
// holding the current config, so an erase/program interrupted by a reset or
// power loss can only damage the copy being written -- the previous copy stays
// valid. Without this, the ~100 ms between erase and program left the config
// page blank (all 0xFF) and every timestamp in the download was lost.
#define CONFIG_ADDRESS_A         0x70000
#define CONFIG_ADDRESS_B         0x71000
#define CONFIG_MAGIC             0x53504C54  // "SPLT"
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

// On-flash form of ConfigData: fixed-width fields plus a magic, a sequence
// number (the higher valid one wins) and a CRC so a blank or half-written page
// is never mistaken for a real config.
struct ConfigRecord {
    uint32_t magic;
    uint32_t sequence;
    uint32_t initialTimestamp;
    uint32_t wakeupInterval;
    char personalId[16];
    uint32_t mode;
    uint32_t crc;
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

bool configValid = false;        // A valid config was loaded or saved
uint32_t configSequence = 0;     // Sequence number of the active config copy
uint32_t configAddress = 0;      // Page holding the active config copy (0 = none)

uint32_t currentIndex = 0;
uint32_t startMillis = 0;       // Track when logging started
OperationMode currentMode = MODE_IDLE;
FlashIAP flash;

#define SERIAL_BAUD_RATE 9600

// Proximity samples discarded before the kept reading, so the logged value comes
// from a settled sensor front end rather than the first post-power-on
// conversion. Sensor config is left at the library default (APDS re-initializes
// on every begin()), so the proximity scale is unchanged.
#define PROX_WARMUP_SAMPLES   2
// Per-conversion bounded wait (ms) so a stuck/absent sensor can never hang.
#define PROX_WAIT_TIMEOUT_MS  1000

// Function declarations
bool loadConfig();
bool saveConfig();
bool saveTemperatureReading(float temperature, uint8_t proximityVal, uint32_t elapsedSeconds);
bool initializeDevice(const uint8_t* packedData);
uint32_t findHighestDataIndex();
void sendReadableData();
void processSerialCommand();
uint8_t readProximitySettled(bool &ready);

uint32_t crc32(const uint8_t* data, size_t len) {
    uint32_t crc = 0xFFFFFFFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int b = 0; b < 8; b++) {
            crc = (crc >> 1) ^ (0xEDB88320 & (0 - (crc & 1)));
        }
    }
    return ~crc;
}

uint32_t configRecordCrc(const ConfigRecord& rec) {
    return crc32((const uint8_t*)&rec, offsetof(ConfigRecord, crc));
}

bool readConfigRecord(uint32_t address, ConfigRecord& rec) {
    if (flash.read(&rec, address, sizeof(ConfigRecord)) != 0) return false;
    return rec.magic == CONFIG_MAGIC &&
           rec.mode <= MODE_LOGGING &&
           rec.crc == configRecordCrc(rec);
}

// Load the newest valid config copy into `config`. Returns false (and leaves
// the in-RAM defaults) if neither page holds a valid config.
bool loadConfig() {
    ConfigRecord a, b;
    bool aValid = readConfigRecord(CONFIG_ADDRESS_A, a);
    bool bValid = readConfigRecord(CONFIG_ADDRESS_B, b);

    const ConfigRecord* rec = nullptr;
    if (aValid && bValid) {
        // Wrap-safe "b is newer than a"
        bool bNewer = (int32_t)(b.sequence - a.sequence) > 0;
        rec = bNewer ? &b : &a;
        configAddress = bNewer ? CONFIG_ADDRESS_B : CONFIG_ADDRESS_A;
    } else if (aValid) {
        rec = &a;
        configAddress = CONFIG_ADDRESS_A;
    } else if (bValid) {
        rec = &b;
        configAddress = CONFIG_ADDRESS_B;
    } else {
        configAddress = 0;
        configValid = false;
        return false;
    }

    config.initialTimestamp = rec->initialTimestamp;
    config.wakeupInterval = rec->wakeupInterval;
    memcpy(config.personalId, rec->personalId, sizeof(config.personalId));
    config.personalId[sizeof(config.personalId) - 1] = '\0';
    config.mode = (OperationMode)rec->mode;
    configSequence = rec->sequence;
    configValid = true;
    return true;
}

// Write `config` to the page not holding the active copy, so the active copy
// survives if this write is interrupted.
bool saveConfig() {
    uint32_t target = (configAddress == CONFIG_ADDRESS_A) ? CONFIG_ADDRESS_B : CONFIG_ADDRESS_A;

    ConfigRecord rec;
    memset(&rec, 0, sizeof(rec));
    rec.magic = CONFIG_MAGIC;
    rec.sequence = configSequence + 1;
    rec.initialTimestamp = config.initialTimestamp;
    rec.wakeupInterval = config.wakeupInterval;
    memcpy(rec.personalId, config.personalId, sizeof(rec.personalId));
    rec.personalId[sizeof(rec.personalId) - 1] = '\0';
    rec.mode = (uint32_t)config.mode;
    rec.crc = configRecordCrc(rec);

    int result = flash.erase(target, FLASH_PAGE_SIZE);
    if (result != 0) return false;

    result = flash.program(&rec, target, sizeof(ConfigRecord));
    if (result != 0) return false;

    ConfigRecord verifyRec;
    if (flash.read(&verifyRec, target, sizeof(ConfigRecord)) != 0 ||
        memcmp(&rec, &verifyRec, sizeof(ConfigRecord)) != 0) {
        return false;
    }

    configAddress = target;
    configSequence = rec.sequence;
    configValid = true;
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
    // Without a valid config the start time is unknown: report UNKNOWN and send
    // each row's raw elapsed seconds (a start time of 0) so the interface can
    // rebuild real timestamps from a start time the user supplies.
    Serial.print("Initial Timestamp,");
    if (configValid) Serial.println(config.initialTimestamp);
    else Serial.println("UNKNOWN");

    Serial.print("Wake-up Interval (Seconds),");
    if (configValid) Serial.println(config.wakeupInterval);
    else Serial.println("UNKNOWN");

    Serial.print("Personal ID,");
    if (configValid) Serial.println(config.personalId);
    else Serial.println("UNKNOWN");
    
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
        uint32_t timestamp = (configValid ? config.initialTimestamp : 0) + data.elapsedSeconds;
        
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
        // Don't save here: writing a default config would replace the real one
        // (and its start time) with a valid-looking record.
        currentMode = MODE_IDLE;
        Serial.println("Flash initialization failed");
        return;
    }
    
    // No valid config (fresh board, or flashed over an older firmware's config
    // format) leaves the device idle until it is initialized from the interface.
    bool haveConfig = loadConfig();
    currentIndex = findHighestDataIndex();

    // Mode transitions
    if (haveConfig && config.mode == MODE_IDLE && currentIndex == 0) {
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
        // Do NOT disable SPI0/SPI1 here. On the nRF52840 they share silicon with
        // the TWI0/TWI1 (I2C) controllers the APDS9960/HS300x sensors use, so
        // disabling them kills the I2C bus in logging mode -- the proximity read
        // then hangs and nothing is ever logged. (Confirmed on hardware.)
        // NRF_SPI0->ENABLE = 0;
        // NRF_SPI1->ENABLE = 0;
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
        
    } else if (haveConfig && config.mode == MODE_LOGGING) {
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

// Read proximity after discarding warm-up samples so the kept value comes from a
// settled front end. Every wait is bounded, so a stuck/absent sensor returns 0
// (far / not covered) instead of hanging the logger. `ready` reports whether a
// real reading was obtained.
uint8_t readProximitySettled(bool &ready) {
    ready = false;
    int raw = 0;
    for (int i = 0; i <= PROX_WARMUP_SAMPLES; i++) {
        bool got = false;
        unsigned long start = millis();
        while (millis() - start < PROX_WAIT_TIMEOUT_MS) {
            if (APDS.proximityAvailable()) {
                got = true;
                break;
            }
        }
        if (!got) return 0;   // timeout on a warm-up sample or the real read
        raw = APDS.readProximity();
    }
    ready = true;
    return (uint8_t)(raw & 0xFF);
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

            // Read proximity after a warm-up discard for a settled value; the
            // read is internally bounded so a stuck/absent sensor can't hang.
            bool proxReady = false;
            uint8_t proximityVal = readProximitySettled(proxReady);
            (void)proxReady;
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
