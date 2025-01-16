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

// Structure
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

    // Parse the packet: "<epoch_time,personal_id,wakeup_interval>"
    char epoch_time_str[20], personal_id_str[10], wakeup_interval_str[10];
    int parsed = sscanf(data_buffer, "<%[^,],%[^,],%[^>]>", epoch_time_str, personal_id_str, wakeup_interval_str);
    initial_timestamp = strtoul(epoch_time_str, NULL, 10);
    personal_id = (uint16_t)strtoul(personal_id_str, NULL, 10);
    wakeup_interval = (uint16_t)strtoul(wakeup_interval_str, NULL, 10);

    if (parsed == 3) {
        Serial.print("[INFO] Received Epoch Time: ");
        Serial.println(initial_timestamp);
        Serial.print("[INFO] Received Personal ID: ");
        Serial.println(personal_id);
        Serial.print("[INFO] Received Wake-up Interval: ");
        Serial.println(wakeup_interval);

        savePersonalID(personal_id);
        saveWakeupInterval(wakeup_interval);
        
        writeNewLogEntry();
        configureWDT();

        Serial.println("[INFO] Data received and logging started.");
        enterLowPowerMode();
    } else {
        Serial.println("[ERROR] Failed to parse data packet.");
    }
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
