#include <Arduino_HS300x.h>
#include "nrf_nvmc.h"
#include "nrf_wdt.h"

// Constants
#define FLASH_START_ADDRESS 0x60000          // Flash start address for logs
#define FLASH_PAGE_SIZE 4096                 // Flash page size
#define FLASH_TOTAL_SIZE 0x80000
#define MAX_LOG_ENTRIES ((FLASH_TOTAL_SIZE - FLASH_START_ADDRESS) / sizeof(TemperatureLogEntry))
#define ALIGN_4(addr) ((addr + 3) & ~3)
#define INITIAL_TIMESTAMP_ADDRESS (FLASH_START_ADDRESS - FLASH_PAGE_SIZE)  // Reserve a safe page for the timestamp
#define PERSONAL_ID_ADDRESS (INITIAL_TIMESTAMP_ADDRESS - FLASH_PAGE_SIZE)
#define WAKEUP_INTERVAL_ADDRESS (PERSONAL_ID_ADDRESS - FLASH_PAGE_SIZE)
#define REQUIRED_WDT_CYCLES_ADDRESS (WAKEUP_INTERVAL_ADDRESS - FLASH_PAGE_SIZE)
#define GPREGRET_CYCLE_COUNT NRF_POWER->GPREGRET
#define DEBUG_GPIO_PIN NRF_GPIO_PIN_MAP(1, 9)  // Pin for debugging

// Enums
enum DeviceMode { LOGGING, RETRIEVAL };

// Structures
struct DateTime {
    uint16_t date;
    uint16_t time;
};

struct TemperatureLogEntry {
    uint16_t index;                          // Log index (2 bytes)
    int16_t temperature;                     // Scaled temperature (2 bytes)
};

// Global Variables
volatile DeviceMode current_mode = LOGGING;  // Start in logging mode
uint32_t initial_timestamp = 0;
uint16_t log_index = 0;
uint16_t personal_id = 0;
uint16_t wakeup_interval = 0;
uint8_t required_wdt_cycles = 1;
DateTime current_time;

////////////////////////////
/* Low Power Mode Related */
////////////////////////////

// Custom WDT Interrupt Handler
void Custom_WDT_IRQHandler() {
    if (NRF_WDT->EVENTS_TIMEOUT) {
        NRF_WDT->EVENTS_TIMEOUT = 0;         // Clear WDT timeout event
        
        loadRequiredWdtCycles();
        uint8_t wdt_cycle_count = GPREGRET_CYCLE_COUNT;
        wdt_cycle_count++;

        if (wdt_cycle_count >= required_wdt_cycles) {
            wdt_cycle_count = 0;
            GPREGRET_CYCLE_COUNT = 0;

            nrf_gpio_pin_set(DEBUG_GPIO_PIN);
        } else {
            GPREGRET_CYCLE_COUNT = wdt_cycle_count;
            NRF_WDT->RR[0] = WDT_RR_RR_Reload;
            enterLowPowerMode();
        }
    }
}

// Remap the WDT Interrupt Vector Address
void remapWDTInterrupt() {
    uint32_t *vectorTable = (uint32_t *)SCB->VTOR;  // Get vector table base address
    vectorTable[WDT_IRQn + 16] = (uint32_t)Custom_WDT_IRQHandler;  // Remap WDT interrupt
}

// Configure the WDT
void configureWDT() {
    uint16_t wdt_timeout_seconds;

    // Map the wakeup_interval to WDT timeout and required cycles
    if (wakeup_interval == 300) {  // 5 min
        wdt_timeout_seconds = 300;
        required_wdt_cycles = 1;
    } else if (wakeup_interval == 600) {  // 10 min
        wdt_timeout_seconds = 300;
        required_wdt_cycles = 2;
    } else if (wakeup_interval == 1800) {  // 30 min
        wdt_timeout_seconds = 450;
        required_wdt_cycles = 4;
    } else if (wakeup_interval == 3600) {  // 1 hour
        wdt_timeout_seconds = 450;
        required_wdt_cycles = 8;
    } else {
        wdt_timeout_seconds = 300;  // Default to 5 min
        required_wdt_cycles = 1;
        Serial.println("[WARNING] Invalid wakeup interval. Defaulting to 5 min.");
    }

    saveRequiredWdtCycles(required_wdt_cycles);

    NRF_WDT->CONFIG = WDT_CONFIG_SLEEP_Run << WDT_CONFIG_SLEEP_Pos;  // Run in all modes
    NRF_WDT->CRV = (wdt_timeout_seconds * 32768) - 1;                      // WDT timeout in ticks
    NRF_WDT->RREN |= WDT_RREN_RR0_Msk;                               // Enable reload register
    NRF_WDT->TASKS_START = 1;                                        // Start the WDT

    // Enable WDT interrupt
    remapWDTInterrupt();                                             // Remap the interrupt
    NVIC_ClearPendingIRQ(WDT_IRQn);
    NVIC_SetPriority(WDT_IRQn, 3);
    NVIC_EnableIRQ(WDT_IRQn);
}

// Configure LFCLK
void configureLFCLK() {
    NRF_CLOCK->LFCLKSRC = CLOCK_LFCLKSRC_SRC_Xtal;
    NRF_CLOCK->TASKS_LFCLKSTART = 1;
    while (!NRF_CLOCK->EVENTS_LFCLKSTARTED);
    NRF_CLOCK->EVENTS_LFCLKSTARTED = 0;
}

void enterLowPowerMode() {
    Serial.println("[INFO] Entering LOW POWER MODE...");
    nrf_gpio_pin_clear(DEBUG_GPIO_PIN);
    HS300x.end();
    Serial.flush();

    NRF_UART0->ENABLE = 0;
    NRF_SPI0->ENABLE = 0;
    NRF_TWI0->ENABLE = 0;
    NRF_CLOCK->TASKS_HFCLKSTOP = 1;
    NRF_POWER->TASKS_LOWPWR = 1;

    __WFE();
    __SEV();
    __WFE();
}

/////////////////
/* Log Related */
/////////////////

void eraseFlashLogs() {
    // Erase initial timestamp
    __disable_irq();
    nrf_nvmc_page_erase(ALIGN_4(INITIAL_TIMESTAMP_ADDRESS));
    nrf_nvmc_page_erase(ALIGN_4(PERSONAL_ID_ADDRESS));
    nrf_nvmc_page_erase(ALIGN_4(WAKEUP_INTERVAL_ADDRESS));
    __enable_irq();

    // Erase log entries
    for (uint32_t addr = FLASH_START_ADDRESS; addr < FLASH_START_ADDRESS + (MAX_LOG_ENTRIES * sizeof(TemperatureLogEntry)); addr += FLASH_PAGE_SIZE) {
        __disable_irq();
        nrf_nvmc_page_erase(addr);
        __enable_irq();
    }
    Serial.println("[INFO] Flash memory erased. Logs cleared.");
}

bool isFlashFull() {
    return log_index >= (MAX_LOG_ENTRIES-1);
}

void writeNewLogEntry() {
    if (isFlashFull()) {
        Serial.println("[ERROR] Flash is full. Logging halted.");
        current_mode = RETRIEVAL;
        return; // Stop writing
    }

    if (initial_timestamp == 0xFFFFFFFF) {
        Serial.println("[ERROR] Initial timestamp missing.");
        return;
    }

    recoverLastLogIndex();

    TemperatureLogEntry newEntry = {
      .index = log_index,
      .temperature = (int16_t)(HS300x.readTemperature() * 100)
    };

    uint32_t newAddress = ALIGN_4(FLASH_START_ADDRESS + (log_index * sizeof(TemperatureLogEntry)));
    
    __disable_irq();
    nrf_nvmc_write_words(newAddress, (const uint32_t *)&newEntry, sizeof(TemperatureLogEntry) / 4);
    NRF_WDT->RR[0] = WDT_RR_RR_Reload;  // Reset the watchdog timer to prevent unexpected reset
    __enable_irq();

    log_index++;
    Serial.println("[INFO] New log entry recorded.");
}

void recoverLastLogIndex() {
  for (uint32_t i=0; i<MAX_LOG_ENTRIES; i++) {
    uint32_t address = FLASH_START_ADDRESS + (i * sizeof(TemperatureLogEntry));
    TemperatureLogEntry entry;
    memcpy(&entry, (const void *)address, sizeof(TemperatureLogEntry));
    if (entry.index == 0xFFFF) {
        log_index = i;  // Restore the last valid index
        break;
    }
  }
}

void retrieveLogs() {
    // Load the flash-stored objects
    loadInitialTimestamp();
    loadPersonalID();
    loadWakeupInterval();

    // Print header for easier parsing
    Serial.println("[INFO] Starting data retrieval...");
    Serial.print("Personal ID:");
    Serial.println(personal_id);
    Serial.print("Wake-up Interval (seconds):");
    Serial.println(wakeup_interval);
    Serial.print("Initial Timestamp:");
    Serial.println(initial_timestamp);

    for (uint32_t i = 0; i < MAX_LOG_ENTRIES; i++) {
        uint32_t address = FLASH_START_ADDRESS + (i * sizeof(TemperatureLogEntry));
        TemperatureLogEntry entry;

        // Read log entry from flash
        memcpy(&entry, (const void *)address, sizeof(TemperatureLogEntry));

        // Check if the entry is valid
        if (entry.index == 0xFFFF || entry.index == 0xFFFFFFFF) {
            break;
        }

        Serial.print(entry.index);
        Serial.print(",");
        Serial.println(entry.temperature / 100.0);
    }
    Serial.println("End of data.");
}

//////////////////////
/* DateTime Related */
//////////////////////

bool setDateTime(const char* timestamp) {
    Serial.print("[DEBUG] Received timestamp: ");
    Serial.println(timestamp);

    uint8_t year, month, day, hour, minute;
    int parsed = sscanf(timestamp, "%2hhu%2hhu%2hhu %2hhu:%2hhu", &year, &month, &day, &hour, &minute);

    if (parsed != 5 || month < 1 || month > 12 || day < 1 || day > 31 || hour > 23 || minute > 59) {
        Serial.println("[ERROR] Invalid datetime format. Please use YYYY-MM-DD HH:MM.");
        return false;
    }

    current_time.date = encodeDate(year, month, day);
    current_time.time = encodeTime(hour, minute);
    initial_timestamp = encodeTimestamp(current_time);

    __disable_irq();
    nrf_nvmc_write_words(INITIAL_TIMESTAMP_ADDRESS, &initial_timestamp, 1);
    __enable_irq();

    logCurrentTime();

    return true;
}

void readSerialInput(char* buffer, size_t length) {
    uint8_t index = 0;
    while (true) {
        if (Serial.available()) {
            char c = Serial.read();
            if (c == '\n' || index >= length - 1) {
                buffer[index] = '\0';
                break;
            }
            buffer[index++] = c;
        }
    }
}

void setupLoggingMode() {
    current_mode = LOGGING;
    configureLFCLK();

    Serial.println("READY_FOR_DATA");
    Serial.flush();
    while (Serial.available()) {
        Serial.read();  // Clear any residual data
    }

    char data_buffer[50] = {0};
    readSerialInput(data_buffer, sizeof(data_buffer));

    // Parse the packet: "<timestamp,personal_id,wakeup_interval>"
    char timestamp[20], personal_id_str[10], wakeup_interval_str[10];
    int parsed = sscanf(data_buffer, "<%[^,],%[^,],%[^>]>", timestamp, personal_id_str, wakeup_interval_str);
    personal_id = (uint16_t)strtoul(personal_id_str, NULL, 10);
    wakeup_interval = (uint16_t)strtoul(wakeup_interval_str, NULL, 10);

    if (parsed == 3) {
        Serial.print("[INFO] Received Timestamp: ");
        Serial.println(timestamp);
        Serial.print("[INFO] Received Personal ID: ");
        Serial.println(personal_id);
        Serial.print("[INFO] Received Wake-up Interval: ");
        Serial.println(wakeup_interval);

        // Set DateTime
        if (setDateTime(timestamp)) {
            Serial.println("[INFO] Datetime set successfully.");
            writeNewLogEntry();
        } else {
            Serial.println("[ERROR] Failed to set datetime.");
        }

        savePersonalID(personal_id);
        saveWakeupInterval(wakeup_interval);

        configureWDT();

        Serial.println("[INFO] Data received and logging started.");
        enterLowPowerMode();
    } else {
        Serial.println("[ERROR] Failed to parse data packet.");
    }
}

uint16_t encodeDate(uint16_t year, uint8_t month, uint8_t day) {
    year %= 100;  // Keep the last two digits of the year (e.g., 2025 -> 25)
    return (year << 9) | (month << 5) | day;
}

uint16_t encodeTime(uint8_t hour, uint8_t minute) {
    return (hour << 8) | minute;
}

void decodeDate(uint16_t encodedDate, uint16_t &year, uint8_t &month, uint8_t &day) {
    year = (encodedDate >> 9) + 2000;  // Add 2000 to get the full year
    month = (encodedDate >> 5) & 0x0F;
    day = encodedDate & 0x1F;
}

void decodeTime(uint16_t encodedTime, uint8_t &hour, uint8_t &minute) {
    hour = encodedTime >> 8;
    minute = encodedTime & 0xFF;
}

uint32_t encodeTimestamp(const DateTime &dt) {
    const uint16_t days_in_month[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    uint32_t days = 0;

    // Decode the `date` and `time` fields
    uint16_t year;
    uint8_t month, day, hour, minute;
    decodeDate(dt.date, year, month, day);
    decodeTime(dt.time, hour, minute);

    // Calculate the total days for previous years
    for (uint16_t y = 1970; y < year; y++) {
        days += (y % 4 == 0 && (y % 100 != 0 || y % 400 == 0)) ? 366 : 365;
    }

    // Calculate the total days for previous months in the current year
    for (uint8_t m = 1; m < month; m++) {
        days += days_in_month[m - 1];
        if (m == 2 && (year % 4 == 0 && (year % 100 != 0 || year % 400 == 0))) {
            days++;  // Leap year adjustment
        }
    }

    // Add the days in the current month
    days += (day - 1);

    // Convert total days to seconds and add the time components
    uint32_t seconds = days * 24 * 3600 + hour * 3600 + minute * 60;
    return seconds;
}

void logCurrentTime() {
    uint16_t year = current_time.date >> 9;         // Extract year [15:9]
    uint8_t month = (current_time.date >> 5) & 0x0F; // Extract month [8:5]
    uint8_t day = current_time.date & 0x1F;         // Extract day [4:0]
    uint8_t hour = current_time.time >> 8;          // Extract hour [15:8]
    uint8_t minute = current_time.time & 0xFF;      // Extract minute [7:0]

    char formatted_time[16];
    sprintf(formatted_time, "%02d%02d%02d %02d:%02d", year, month, day, hour, minute);
    Serial.print("[INFO] Initial timestamp stored: ");
    Serial.println(formatted_time);  // Print the formatted date and time
}

////////////
/* Others */
////////////

void savePersonalID(uint16_t id) {
  uint32_t aligned_addr = ALIGN_4(PERSONAL_ID_ADDRESS);
  __disable_irq();
  nrf_nvmc_write_words(aligned_addr, (uint32_t*)&id, 1);
  __enable_irq();
  Serial.println("[INFO] Personal ID saved to flash.");
}

void saveWakeupInterval(uint16_t interval) {
  uint32_t aligned_addr = ALIGN_4(WAKEUP_INTERVAL_ADDRESS);
  __disable_irq();
  nrf_nvmc_write_words(aligned_addr, (uint32_t*)&interval, 1);
  __enable_irq();
  Serial.println("[INFO] Wake-up interval saved to flash.");
}

// Load personal ID from flash
void loadInitialTimestamp() {
    memcpy(&initial_timestamp, (const void*)INITIAL_TIMESTAMP_ADDRESS, sizeof(initial_timestamp));
    if (initial_timestamp == 0xFFFFFFFF) {
        Serial.println("[ERROR] No initial timestamp found.");
        return;
    } else {
        Serial.print("[INFO] Loaded initial timestamp: ");
        Serial.println(initial_timestamp);
    }
}

// Load personal ID from flash
void loadPersonalID() {
    memcpy(&personal_id, (const void*)PERSONAL_ID_ADDRESS, sizeof(personal_id));
    if (personal_id == 0xFFFF) {
        Serial.println("[INFO] No personal ID found. Using default.");
        personal_id = 0;
    } else {
        Serial.print("[INFO] Loaded personal ID: ");
        Serial.println(personal_id);
    }
}

void loadWakeupInterval() {
    memcpy(&wakeup_interval, (const void*)WAKEUP_INTERVAL_ADDRESS, sizeof(wakeup_interval));
    if (wakeup_interval == 0xFFFF) {
        Serial.println("[INFO] No wake-up interval found. Using default.");
        wakeup_interval = 60;  // Default to 60 seconds
    } else {
        Serial.print("[INFO] Loaded wake-up interval: ");
        Serial.println(wakeup_interval);
    }
}

void saveRequiredWdtCycles(uint16_t cycles) {
    uint32_t aligned_addr = ALIGN_4(REQUIRED_WDT_CYCLES_ADDRESS);
    __disable_irq();
    nrf_nvmc_write_words(aligned_addr, (uint32_t*)&cycles, 1);
    __enable_irq();
    Serial.println("[INFO] Required WDT cycles saved to flash.");
}

void loadRequiredWdtCycles() {
    memcpy(&required_wdt_cycles, (const void*)REQUIRED_WDT_CYCLES_ADDRESS, sizeof(required_wdt_cycles));
    if (required_wdt_cycles == 0xFFFF) {
        Serial.println("[INFO] No saved WDT cycles found. Using default.");
        required_wdt_cycles = 1;
    } else {
        Serial.print("[INFO] Loaded required WDT cycles: ");
        Serial.println(required_wdt_cycles);
    }
}

void setupRetrievalMode() {
    current_mode = RETRIEVAL;
    Serial.println("[INFO] Entered retrieval mode.");
}

void setup() {
    nrf_gpio_cfg_output(DEBUG_GPIO_PIN);
    HS300x.begin();

    // Check reset reason
    uint32_t reset_reason = NRF_POWER->RESETREAS;
    NRF_POWER->RESETREAS = reset_reason;

    Serial.begin(115200);

    if (reset_reason & POWER_RESETREAS_DOG_Msk) {
        Serial.println("[INFO] Woke up from WDT.");
        recoverLastLogIndex();
        loadWakeupInterval();
        writeNewLogEntry();

        // Reconfigure LFCLK and WDT for next cycle
        configureLFCLK();
        configureWDT();
        enterLowPowerMode();
    } else {
        Serial.println("Enter mode: [l] for logging, or [r] for retrieval");
        while (true) {
            if (Serial.available()) {
                char mode = Serial.read();
                if (mode == 'l') {
                    eraseFlashLogs();
                    setupLoggingMode();
                    return;
                } else if (mode == 'r') {
                    setupRetrievalMode();
                    retrieveLogs();
                    return;
                }
            }
        }
    }
}

void loop() {
}
