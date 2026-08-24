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
OperationMode currentMode = MODE_IDLE;
// When true, logging runs in an observable, USB-friendly mode (serial stays up,
// plain delay() between samples) instead of the low-power deep-sleep path. Used
// for bench testing while plugged into a host.
bool benchLogging = false;
FlashIAP flash;

#define SERIAL_BAUD_RATE 9600

// APDS9960 I2C address and register map (direct access for explicit config)
#define APDS9960_I2C_ADDR        0x39
#define APDS9960_REG_PPULSE      0x8E   // Proximity pulse count/length
#define APDS9960_REG_CONTROL     0x8F   // LED drive / proximity gain / ALS gain
#define APDS9960_REG_POFFSET_UR  0x9D   // Proximity offset, up/right photodiodes
#define APDS9960_REG_POFFSET_DL  0x9E   // Proximity offset, down/left photodiodes

// Sensor availability wait timeout, in RTC (1 Hz) seconds
#define PROX_WAIT_TIMEOUT_S      2
// Number of proximity samples discarded to let the analog front-end settle
#define PROX_WARMUP_SAMPLES      2

// Function declarations
bool saveConfig();
bool saveTemperatureReading(float temperature, uint8_t proximityVal, uint32_t elapsedSeconds);
bool initializeDevice(const uint8_t* packedData);
uint32_t findHighestDataIndex();
void sendReadableData();
void processSerialCommand();
void startLoggingClock();
uint32_t loggingElapsedSeconds();
void sleepUntilSecond(uint32_t targetSecond);
void configureAPDS();
uint8_t readProximityStable();
bool usbConnected();
bool isConfigured();
void enterLowPowerLogging();

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
                        // Init runs over USB, where SYSTEMOFF is only emulated
                        // (and left the board in a confusing state). Stay idle
                        // and interactive instead; the device begins logging on
                        // its own when next powered from battery. Unplug to
                        // deploy.
                        Serial.println("INITIALIZED");
                        currentMode = MODE_IDLE;
                        config.mode = MODE_IDLE;
                        digitalWrite(LEDR, HIGH);
                        digitalWrite(LEDG, LOW);
                        digitalWrite(LEDB, HIGH);
                    } else {
                        Serial.println("INIT_FAILED");
                    }
                }
                break;
            case 'l':
                // Start logging on demand while on USB (bench testing). Keeps
                // serial alive and prints each reading; does not power down.
                if (isConfigured()) {
                    Serial.println("LOGGING_STARTED");
                    benchLogging = true;
                    currentMode = MODE_LOGGING;
                    config.mode = MODE_LOGGING;
                    digitalWrite(LED_PWR, HIGH);
                    startLoggingClock();
                } else {
                    Serial.println("NEED_CONFIGURATION");
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

// ---------------------------------------------------------------------------
// Low-power timekeeping and sleep
//
// RTC0 is reserved for the SoftDevice (BLE) and RTC1 drives the mbed RTOS tick,
// so RTC2 is the only free RTC. We run it at 1 Hz off the already-running LFCLK
// (32.768 kHz) and use its 24-bit COUNTER as the master "seconds since logging
// started" clock. This replaces millis() for logging timing: during deep sleep
// we mask interrupts, which freezes the RTOS tick (and therefore millis()), but
// RTC2 keeps counting, so elapsed time stays accurate across sleeps.
// ---------------------------------------------------------------------------
void startLoggingClock() {
    // LFCLK is already running (the RTOS tick depends on it), so we only touch
    // RTC2 here and leave the clock source alone to avoid disturbing RTC1.
    NRF_RTC2->TASKS_STOP  = 1;
    NRF_RTC2->TASKS_CLEAR = 1;
    NRF_RTC2->PRESCALER   = 32767;   // 32768 / (32767 + 1) = 1 Hz -> 1 tick/sec
    NRF_RTC2->INTENCLR    = 0xFFFFFFFF;
    NRF_RTC2->EVTENCLR    = 0xFFFFFFFF;
    NRF_RTC2->EVENTS_COMPARE[0] = 0;
    NRF_RTC2->TASKS_START = 1;
}

uint32_t loggingElapsedSeconds() {
    return NRF_RTC2->COUNTER & 0x00FFFFFF;   // 24-bit counter, ~194 days at 1 Hz
}

// Enter System-ON deep sleep until RTC2 reaches targetSecond. Interrupts are
// masked so the RTOS tick cannot wake us ~1000x/second; instead SEVONPEND lets
// the pending RTC2 compare wake __WFE while the ISR itself never vectors.
void sleepUntilSecond(uint32_t targetSecond) {
    targetSecond &= 0x00FFFFFF;

    // Already there (e.g. sampling overran the interval): don't sleep.
    if (loggingElapsedSeconds() >= targetSecond) {
        return;
    }

    NRF_RTC2->CC[0] = targetSecond;
    NRF_RTC2->EVENTS_COMPARE[0] = 0;
    NRF_RTC2->EVTENSET = RTC_EVTENSET_COMPARE0_Msk;
    NRF_RTC2->INTENSET = RTC_INTENSET_COMPARE0_Msk;

    NVIC_ClearPendingIRQ(RTC2_IRQn);
    NVIC_EnableIRQ(RTC2_IRQn);
    SCB->SCR |= SCB_SCR_SEVONPEND_Msk;   // pending IRQ generates an event for WFE

    __disable_irq();
    while (loggingElapsedSeconds() < targetSecond &&
           NRF_RTC2->EVENTS_COMPARE[0] == 0) {
        __DSB();
        __WFE();
        __SEV();   // clear any stale event so the following WFE truly sleeps
        __WFE();
    }

    // Tear down before re-enabling IRQs so the (handler-less) RTC2 IRQ can't fire.
    NRF_RTC2->INTENCLR = RTC_INTENSET_COMPARE0_Msk;
    NRF_RTC2->EVTENCLR = RTC_EVTENSET_COMPARE0_Msk;
    NRF_RTC2->EVENTS_COMPARE[0] = 0;
    NVIC_ClearPendingIRQ(RTC2_IRQn);
    NVIC_DisableIRQ(RTC2_IRQn);
    __enable_irq();
}

// ---------------------------------------------------------------------------
// Proximity sensor configuration and drift mitigation
//
// The bundled Arduino_APDS9960 library leaves gain/LED-drive/offset at library
// defaults, which lets the proximity baseline wander over long deployments
// (enclosure crosstalk plus thermal drift of the IR LED and photodiode as the
// splint warms). We program these explicitly on every begin() so each reading
// is taken under identical, settled conditions, and use a lower LED drive to
// cut LED self-heating (a real drift source) while still easily detecting a
// splint pressed against skin.
// ---------------------------------------------------------------------------
static void writeAPDS(uint8_t reg, uint8_t value) {
    Wire.beginTransmission(APDS9960_I2C_ADDR);
    Wire.write(reg);
    Wire.write(value);
    Wire.endTransmission();
}

void configureAPDS() {
    // CONTROL: LDRIVE=0b11 (12.5 mA IR LED), PGAIN=0b10 (4x), AGAIN=0b00 -> 0xC8
    writeAPDS(APDS9960_REG_CONTROL, 0xC8);
    // PPULSE: PPLEN=0b01 (8 us pulses), PPULSE=7 (8 pulses) -> 0x47
    writeAPDS(APDS9960_REG_PPULSE, 0x47);
    // Explicit, deterministic proximity offsets. If the splint housing produces
    // measurable crosstalk, raise these (signed-magnitude, bit7 = sign) after a
    // bench measurement of the unworn baseline.
    writeAPDS(APDS9960_REG_POFFSET_UR, 0x00);
    writeAPDS(APDS9960_REG_POFFSET_DL, 0x00);
}

// Read proximity after discarding warm-up samples, with a bounded wait so a
// stalled sensor returns a benign value instead of freezing all logging.
uint8_t readProximityStable() {
    for (int i = 0; i <= PROX_WARMUP_SAMPLES; i++) {
        uint32_t waitStart = loggingElapsedSeconds();
        while (!APDS.proximityAvailable()) {
            if (loggingElapsedSeconds() - waitStart >= PROX_WAIT_TIMEOUT_S) {
                return 0;   // treat a timeout as "far / not covered"
            }
        }
        int raw = APDS.readProximity();
        if (i == PROX_WARMUP_SAMPLES) {
            return (uint8_t)(raw & 0xFF);
        }
    }
    return 0;
}

// ---------------------------------------------------------------------------
// Boot-mode decision helpers
//
// The mode is decided from whether a USB host is supplying power, not from a
// persisted toggle flag. On the nRF52840 a normal USB-CDC open does not reset
// the board, so a flip-flop that only re-evaluates in setup() was unreliable
// and could leave a just-initialized device booting into logging with USB
// disabled (invisible to the host). VBUSDETECT is on-chip and reflects the
// cable directly.
// ---------------------------------------------------------------------------
bool usbConnected() {
    return (NRF_POWER->USBREGSTATUS & POWER_USBREGSTATUS_VBUSDETECT_Msk) != 0;
}

// True once the device has been initialized with a valid config. Blank flash
// reads back as all-0xFF, so guard against those sentinel values.
bool isConfigured() {
    return config.initialTimestamp != 0xFFFFFFFF &&
           config.wakeupInterval > 0 &&
           config.wakeupInterval <= 86400UL;   // sane upper bound: <= 1 day
}

// Power down unused peripherals and hand timing to the RTC clock, then drop
// serial. Used only for battery (host-less) deployment logging.
void enterLowPowerLogging() {
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

    Serial.end();
    startLoggingClock();
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

    // Mode is chosen from USB presence, not a persisted toggle. Recorded data is
    // preserved on every idle boot; only the 'i' command erases it.
    if (usbConnected()) {
        // On a host: stay interactive so init/download/status always work, and
        // allow bench logging on demand via the 'l' command. Never auto-log or
        // disable USB here.
        currentMode = MODE_IDLE;
        config.mode = MODE_IDLE;
        digitalWrite(LEDR, HIGH);
        digitalWrite(LEDG, LOW);
        digitalWrite(LEDB, HIGH);
        Serial.println("Ready for Connection");
    } else if (isConfigured()) {
        // On battery and configured: deploy into low-power logging.
        currentMode = MODE_LOGGING;
        benchLogging = false;
        config.mode = MODE_LOGGING;
        enterLowPowerLogging();
    } else {
        // On battery but never configured: nothing to log. Stay idle.
        currentMode = MODE_IDLE;
        config.mode = MODE_IDLE;
    }
}

void loop() {
    switch (currentMode) {
        case MODE_LOGGING: {
            // Absolute wake schedule (seconds since logging start) so cadence
            // does not drift with per-sample processing time.
            static uint32_t nextWakeSecond = 0;

            // Actual elapsed time since logging started, from the RTC clock.
            uint32_t elapsedSeconds = loggingElapsedSeconds();

            // Initialize sensors and apply explicit, drift-resistant config.
            APDS.begin();
            configureAPDS();
            HS300x.begin();
            delay(50);

            // Read sensors (proximity with warm-up discard and a bounded wait).
            uint8_t proximityVal = readProximityStable();
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

            // Bench mode: echo the reading so it can be watched over serial.
            if (benchLogging) {
                Serial.print(elapsedSeconds);
                Serial.print(",");
                Serial.print(temperature, 2);
                Serial.print(",");
                Serial.println(proximityVal);
            }

            // Advance the schedule by one interval.
            nextWakeSecond += config.wakeupInterval;

            if (benchLogging) {
                // Stay powered and responsive (USB serial alive) between samples.
                while (loggingElapsedSeconds() < nextWakeSecond) {
                    delay(50);
                }
            } else {
                // Low-power deep sleep until the next sample is due.
                digitalWrite(LED_PWR, LOW);
                sleepUntilSecond(nextWakeSecond);
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