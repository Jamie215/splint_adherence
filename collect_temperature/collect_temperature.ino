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
static volatile bool rtc2Fired = false;   // set by the RTC2 wake interrupt

#define SERIAL_BAUD_RATE 9600

// DIAGNOSTIC SWITCH. Set to 1 to build an observable logging mode: USB/serial is
// kept alive during logging and each cycle prints what the sensors did, and the
// proximity wait times out instead of hanging. Keep at 0 for normal low-power
// deployment; flip to 1 only for bench debugging.
#define DEBUG_LOGGING 0

// Proximity samples discarded before the kept reading, so the logged value comes
// from a settled sensor front end rather than the first post-power-on
// conversion. The sensor config itself is left at the library default (APDS
// re-initializes on every begin()), so the proximity scale is unchanged.
#define PROX_WARMUP_SAMPLES   2
// Per-conversion bounded wait (ms) so a stuck/absent sensor can never hang.
#define PROX_WAIT_TIMEOUT_MS  1000

// Function declarations
bool saveConfig();
bool saveTemperatureReading(float temperature, uint8_t proximityVal, uint32_t elapsedSeconds);
bool initializeDevice(const uint8_t* packedData);
uint32_t findHighestDataIndex();
void sendReadableData();
void processSerialCommand();
uint8_t readProximitySettled(bool &ready);
void lowPowerWait(uint32_t ms);

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

#if !DEBUG_LOGGING
        // Power saving configurations (skipped in DEBUG so USB/serial survive).
        NRF_USBD->ENABLE = 0;
        NRF_CLOCK->TASKS_HFCLKSTOP = 1;
        NRF_SAADC->ENABLE = 0;
        NRF_PWM0->ENABLE = 0;
        NRF_PWM1->ENABLE = 0;
        NRF_PWM2->ENABLE = 0;
        NRF_PDM->ENABLE = 0;
        NRF_I2S->ENABLE = 0;
        // Do NOT disable SPI0/SPI1 here. On the nRF52840 they share silicon
        // with the TWI0/TWI1 (I2C) controllers the APDS9960/HS300x sensors use;
        // disabling them killed the I2C bus in logging mode, hanging the
        // proximity read so nothing was ever logged. Confirmed on hardware.
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
#endif

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
#if !DEBUG_LOGGING
        Serial.end();
#else
        Serial.println("DEBUG: entering logging mode (serial kept alive)");
#endif
        startMillis = millis();  // Initialize timing reference
    }
}

// RTC2 fires this at the end of a low-power wait. Clear the event and flag it so
// the __WFI loop in lowPowerWait() exits.
extern "C" void RTC2_IRQHandler(void) {
    if (NRF_RTC2->EVENTS_COMPARE[0]) {
        NRF_RTC2->EVENTS_COMPARE[0] = 0;
        NRF_RTC2->INTENCLR = RTC_INTENCLR_COMPARE0_Msk;
        rtc2Fired = true;
    }
}

// Sleep for `ms` in the nRF52840's low-power System-ON state instead of the
// shallow sleep delay() leaves the chip in. RTC2 (a free RTC; RTC0 is the
// SoftDevice, RTC1 the mbed tick) runs at 1024 Hz off the 32 kHz LFCLK and wakes
// the CPU from __WFI at the deadline. Interrupts stay enabled throughout, so the
// RTOS clock (millis) and everything else keep running normally -- only the CPU
// idles deeper. HFCLK was already stopped when logging mode was entered.
void lowPowerWait(uint32_t ms) {
    if (ms == 0) return;
    uint32_t ticks = (uint32_t)(((uint64_t)ms * 1024) / 1000);  // 1024 Hz
    if (ticks == 0) ticks = 1;
    if (ticks > 0xFFFFFF) ticks = 0xFFFFFF;   // 24-bit counter (~4.5 h) cap

    rtc2Fired = false;
    NRF_RTC2->TASKS_STOP = 1;
    NRF_RTC2->TASKS_CLEAR = 1;
    NRF_RTC2->PRESCALER = 31;                 // 32768/(31+1) = 1024 Hz
    NRF_RTC2->CC[0] = ticks;
    NRF_RTC2->EVENTS_COMPARE[0] = 0;
    NRF_RTC2->INTENSET = RTC_INTENSET_COMPARE0_Msk;
    NVIC_ClearPendingIRQ(RTC2_IRQn);
    NVIC_EnableIRQ(RTC2_IRQn);
    NRF_RTC2->TASKS_START = 1;

    while (!rtc2Fired) {
        __WFI();   // other interrupts may wake us early; just re-enter
    }

    NRF_RTC2->TASKS_STOP = 1;
    NVIC_DisableIRQ(RTC2_IRQn);
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
            int apdsOk = APDS.begin();
            int hsOk = HS300x.begin();
            delay(50);

            // Read proximity after a warm-up discard for a settled value; the
            // read is internally bounded so a stuck/absent sensor can't hang.
            bool proxReady = false;
            uint8_t proximityVal = readProximitySettled(proxReady);
            float temperature = HS300x.readTemperature();

#if DEBUG_LOGGING
            Serial.print("DEBUG cycle: APDS.begin=");
            Serial.print(apdsOk);
            Serial.print(" HS300x.begin=");
            Serial.print(hsOk);
            Serial.print(" proxReady=");
            Serial.print(proxReady);
            Serial.print(" prox=");
            Serial.print(proximityVal);
            Serial.print(" temp=");
            Serial.println(temperature, 2);
#else
            (void)apdsOk;
            (void)hsOk;
#endif

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
#if DEBUG_LOGGING
                delay(sleepDuration);          // keep serial alive for bench debug
#else
                lowPowerWait(sleepDuration);   // true low-power sleep between samples
#endif
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