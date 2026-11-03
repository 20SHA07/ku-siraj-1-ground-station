/*
  KU-SIRAJ 1 - SATELLITE side: ESP32 (DOIT DEVKIT V1) + RA-02 SX1278 433 MHz, RadioLib
  Sends one compact JSON telemetry packet per second over LoRa to lora_ground_rx.

  RA-02 wiring (same as the team's RadioLib test, 3.3 V only, antenna fitted):
    NSS/CS GPIO5   DIO0 GPIO26   RST GPIO14   SCK GPIO18   MISO GPIO19   MOSI GPIO23
  Optional INA219 (Adafruit INA219 library): SDA GPIO21, SCL GPIO22, shunt in the LOAD branch.
  Battery voltage: 100k/100k divider -> GPIO34 (set HAS_BATTERY_DIVIDER to false if not wired).
*/
#include <SPI.h>
#include <RadioLib.h>
#include <Wire.h>
#if __has_include(<Adafruit_INA219.h>)
  #include <Adafruit_INA219.h>
  #define HAVE_INA219_LIB 1
  Adafruit_INA219 ina219;
#endif

// Radio settings: must match lora_ground_rx.
const float FREQ_MHZ = 433.0;   // 433 MHz ISM band (check UAE TDRA short-range-device limits)
const float BW_KHZ = 125.0;
const uint8_t SF = 9;
const uint8_t CR = 7;
const uint8_t SYNC_WORD = 0x12;
const int8_t TX_POWER_DBM = 10;  // 10 mW, low power for a ground demo

const bool HAS_BATTERY_DIVIDER = true;
const int BATTERY_ADC_PIN = 34;
const float DIVIDER_RATIO = 2.0;
const char* DEVICE_ID = "ku-siraj-1";

SX1278 radio = new Module(5, 26, 14, RADIOLIB_NC);
bool inaOk = false;
unsigned long packetId = 0;

float readBatteryVoltage() {
  uint32_t mv = 0;
  for (int i = 0; i < 16; i++) mv += analogReadMilliVolts(BATTERY_ADC_PIN);
  return (mv / 16.0f) / 1000.0f * DIVIDER_RATIO;
}

void setup() {
  Serial.begin(115200);
  delay(500);
  SPI.begin(18, 19, 23, 5);
#ifdef HAVE_INA219_LIB
  Wire.begin(21, 22);
  inaOk = ina219.begin();
#endif
  analogReadResolution(12);

  int state = radio.begin(FREQ_MHZ, BW_KHZ, SF, CR, SYNC_WORD, TX_POWER_DBM);
  if (state != RADIOLIB_ERR_NONE) {
    Serial.printf("{\"status\":\"RA-02 init failed, code %d. Check wiring, power, antenna.\"}\n", state);
    while (true) delay(1000);
  }
  radio.setCRC(true);
  Serial.println("{\"status\":\"KU-SIRAJ 1 satellite transmitter ready\"}");
}

void loop() {
  packetId++;
  char body[200];
  int n = snprintf(body, sizeof body, "{\"device_id\":\"%s\",\"packet_id\":%lu", DEVICE_ID, packetId);
#ifdef HAVE_INA219_LIB
  if (inaOk) {
    float busV = ina219.getBusVoltage_V() + ina219.getShuntVoltage_mV() / 1000.0f;
    n += snprintf(body + n, sizeof body - n, ",\"load_voltage_v\":%.3f,\"load_current_ma\":%.1f", busV, ina219.getCurrent_mA());
  }
#endif
  if (HAS_BATTERY_DIVIDER) n += snprintf(body + n, sizeof body - n, ",\"battery_voltage_v\":%.3f", readBatteryVoltage());
  // Add ,"temperature_c":xx.x here once the temperature sensor is wired (send null if a read fails).
  snprintf(body + n, sizeof body - n, "}");

  int state = radio.transmit(body);
  if (state == RADIOLIB_ERR_NONE) Serial.println(body);
  else Serial.printf("{\"status\":\"transmit failed, code %d\"}\n", state);
  delay(1000);
}
