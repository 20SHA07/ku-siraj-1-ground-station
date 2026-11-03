/*
  KU-SIRAJ 1 - SATELLITE side: ESP32-WROOM-32 + SX1278 (Ra-02, 433 MHz) LoRa transmitter

  Reads the sensors and sends one compact JSON packet per second over LoRa.
  The ground station (lora_ground_rx) receives it and passes it to the dashboard.
  An EXAMPLE to adapt: not yet run on the team's board. Confirm pins against the eCAD.

  Library: "LoRa" by Sandeep Mistry, "Adafruit INA219"  (Arduino Library Manager)

  SX1278 -> ESP32 wiring (3.3 V ONLY, never 5 V; always fit the antenna before transmitting):
    VCC 3.3V   GND GND
    NSS  -> GPIO5     SCK  -> GPIO18    MISO -> GPIO19    MOSI -> GPIO23
    RST  -> GPIO14    DIO0 -> GPIO26
  INA219: SDA GPIO21, SCL GPIO22, shunt in series with the LOAD branch.
  Battery: 100k/100k divider -> GPIO34.
*/
#include <SPI.h>
#include <LoRa.h>
#include <Wire.h>
#include <Adafruit_INA219.h>

// ---- radio settings: MUST match lora_ground_rx -------------------------
const long  LORA_FREQ   = 433E6;   // 433 MHz ISM band. Check the UAE (TDRA) short-range-device limits.
const int   TX_POWER    = 10;      // dBm (10 mW). Keep low for a bench/ground demo.
const int   SF          = 9;       // spreading factor 7..12 (higher = longer range, slower)
const long  BANDWIDTH   = 125E3;
const int   SYNC_WORD   = 0x34;    // private network id, same on both ends
// -------------------------------------------------------------------------
const int PIN_NSS = 5, PIN_RST = 14, PIN_DIO0 = 26;
const int BATTERY_ADC_PIN = 34;
const float DIVIDER_RATIO = 2.0;
const char* DEVICE_ID = "ku-siraj-1";

Adafruit_INA219 ina219;
bool inaOk = false;
unsigned long packetId = 0;

float readBatteryVoltage() {
  uint32_t mv = 0;
  for (int i = 0; i < 16; i++) mv += analogReadMilliVolts(BATTERY_ADC_PIN);
  return (mv / 16.0f) / 1000.0f * DIVIDER_RATIO;
}

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);
  inaOk = ina219.begin();
  analogReadResolution(12);

  LoRa.setPins(PIN_NSS, PIN_RST, PIN_DIO0);
  while (!LoRa.begin(LORA_FREQ)) {
    Serial.println("{\"status\":\"lora init failed, check wiring\"}");
    delay(2000);
  }
  LoRa.setTxPower(TX_POWER);
  LoRa.setSpreadingFactor(SF);
  LoRa.setSignalBandwidth(BANDWIDTH);
  LoRa.setSyncWord(SYNC_WORD);
  LoRa.enableCrc();
}

void loop() {
  packetId++;
  // Keep the packet short (well under 255 bytes): no timestamp here, the ground side adds it.
  char body[200];
  int n = snprintf(body, sizeof body, "{\"device_id\":\"%s\",\"packet_id\":%lu", DEVICE_ID, packetId);
  if (inaOk) {
    float busV = ina219.getBusVoltage_V() + ina219.getShuntVoltage_mV() / 1000.0f;
    n += snprintf(body + n, sizeof body - n, ",\"load_voltage_v\":%.3f,\"load_current_ma\":%.1f", busV, ina219.getCurrent_mA());
  } else {
    n += snprintf(body + n, sizeof body - n, ",\"load_voltage_v\":null,\"load_current_ma\":null");
  }
  n += snprintf(body + n, sizeof body - n, ",\"battery_voltage_v\":%.3f", readBatteryVoltage());
  // Add "temperature_c" here once the temperature sensor is chosen (send null if a read fails).
  snprintf(body + n, sizeof body - n, "}");

  LoRa.beginPacket();
  LoRa.print(body);
  LoRa.endPacket();            // blocks until sent (~0.2 s at SF9)
  Serial.println(body);        // also visible on USB for bench debugging
  delay(1000);
}
