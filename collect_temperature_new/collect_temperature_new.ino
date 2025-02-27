#include "mbed.h"
#include "rtos.h"
#include "Wire.h"
#include "nrf.h"
#include "USBSerial.h"
#include "HS300x.h"

using namespace mbed;
using namespace rtos;

#define DEBUG_GPIO_PIN NRF_GPIO_PIN_MAP(1, 9)
#define WAKEUP_INTERVAL_SECONDS 5

// Comment out if not debugging
// #define ENABLE_SERIAL_DEBUG

#ifdef ENABLE_SERIAL_DEBUG
USBSerial serial;
#endif

// Single timer for wake-up
LowPowerTimeout wakeupTimer;
volatile bool wakeupFlag = false;

// Safe callback that just sets a flag
void wakeupCallback() {
  wakeupFlag = true;
}

void optimizePower() {
    // Disable UARTE/UART - big power drain
    NRF_UARTE0->ENABLE = 0;
    NRF_UART0->ENABLE = 0;
    
    // Stop high-frequency clock
    NRF_CLOCK->TASKS_HFCLKSTOP = 1;
    
    // Disable unused analog peripherals  
    NRF_SAADC->ENABLE = 0;
    NRF_PWM0->ENABLE = 0;
    NRF_PWM1->ENABLE = 0;
    NRF_PWM2->ENABLE = 0;
    
    // Disable USB
    #ifndef ENABLE_SERIAL_DEBUG
    NRF_USBD->ENABLE = 0;
    #endif
    
    // Configure SCB for proper deep sleep
    SCB->SCR |= SCB_SCR_SLEEPDEEP_Msk;    // Set SLEEPDEEP bit
    SCB->SCR |= SCB_SCR_SEVONPEND_Msk;    // Set SEVONPEND bit
}

void restoreSystem() {
    // Clear sleep deep bit
    SCB->SCR &= ~SCB_SCR_SLEEPDEEP_Msk;
    SCB->SCR &= ~SCB_SCR_SEVONPEND_Msk;
}

// Enter sleep mode with single wake-up timer
void enterDeepSleep() {
    #ifdef ENABLE_SERIAL_DEBUG
    serial.printf("Entering low power mode\r\n");
    ThisThread::sleep_for(10);
    #endif

    // End I2C communication
    Wire1.end();
    
    // Power off sensors
    digitalWrite(P0_22, LOW);
    digitalWrite(P1_0, LOW);
    
    optimizePower();

    // Reset wake-up flag
    wakeupFlag = false;
    
    // Set up wake-up timer
    wakeupTimer.attach(&wakeupCallback, WAKEUP_INTERVAL_SECONDS);
    
    // Enter sleep mode with safe approach
    while (!wakeupFlag) {
        // Use cortex sleep function with proper parameters for light sleep
        __WFI();
    }

    restoreSystem();
    
    // Restore peripherals for normal operation
    pinMode(P0_14, INPUT_PULLUP);
    pinMode(P0_15, INPUT_PULLUP);
    
    // Power on sensors
    digitalWrite(P0_22, HIGH);
    digitalWrite(P1_0, HIGH);
    ThisThread::sleep_for(10);
    
    // Reinitialize I2C
    Wire1.begin();
    Wire1.setClock(100000);
    
    #ifdef ENABLE_SERIAL_DEBUG
    serial.printf("Woke up from sleep\r\n");
    #endif
}

void setup() {
    // Configure debug pin
    nrf_gpio_cfg_output(DEBUG_GPIO_PIN);
    
    #ifdef ENABLE_SERIAL_DEBUG
    serial.begin(115200);
    ThisThread::sleep_for(1000);
    serial.printf("Starting reliable low power monitoring\r\n");
    #endif

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
    int status = HS300x.begin();
    
    #ifdef ENABLE_SERIAL_DEBUG
    serial.printf("HS300x.begin returned: %d\r\n", status);
    #endif
}

int main() {
    setup();

    while (true) {
        // Clear debug pin
        nrf_gpio_pin_clear(DEBUG_GPIO_PIN);
        
        // Enter low power mode until timer expires
        enterDeepSleep();

        // Set debug pin
        nrf_gpio_pin_set(DEBUG_GPIO_PIN);
        
        // Read temperature
        float temperature = HS300x.readTemperature();
        
        #ifdef ENABLE_SERIAL_DEBUG
        serial.printf("Temperature: %.2f°C\r\n", temperature);
        #endif
        
        // Short delay
        ThisThread::sleep_for(10);
    }
}