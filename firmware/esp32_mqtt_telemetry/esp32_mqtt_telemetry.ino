/*
  KU-SIRAJ 1 - ESP32-WROOM-32 telemetry example (Wi-Fi -> MQTT -> live dashboard)

  An EXAMPLE for the firmware teammate to adapt, not tested on the team's board.
  It sends one JSON packet per second in the dashboard's data contract:
    - over Wi-Fi to the MQTT broker (the hosted dashboard updates live), and
    - over USB serial (for server.py or mqtt_publisher.py --serial when Wi-Fi is not available).

  Libraries (Arduino Library Manager): PubSubClient (Nick O'Leary), Adafruit INA219.
  Board: "ESP32 Dev Module".

  Wiring assumed here (confirm against the eCAD before flashing):
    INA219  SDA -> GPIO21, SCL -> GPIO22, shunt in series with the LOAD branch
    Battery voltage -> 100k/100k divider -> GPIO34 (ADC1, input only)
  One INA219 measures ONE branch. Only send the currents the circuit really measures.
*/
#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_INA219.h>
#include <time.h>

// ---- settings -----------------------------------------------------------
const char* WIFI_SSID     = "YOUR_WIFI";
const char* WIFI_PASSWORD = "YOUR_PASSWORD";      // keep real passwords out of public repos
const char* MQTT_HOST     = "broker.hivemq.com";  // public test broker: anyone can read the topic
const uint16_t MQTT_PORT  = 1883;
const char* TOPIC         = "ku-shihab/ku-siraj-1/telemetry";
const char* STATUS_TOPIC  = "ku-shihab/ku-siraj-1/status";
const char* DEVICE_ID     = "ku-siraj-1";

const int   BATTERY_ADC_PIN = 34;
const float DIVIDER_RATIO   = 2.0;     // 100k/100k divider halves the battery voltage
const bool  HAS_TEMP_SENSOR = false;   // set true and fill readTemperature() once the sensor is chosen
// -------------------------------------------------------------------------

WiFiClient net;
PubSubClient mqtt(net);
Adafruit_INA219 ina219;
bool inaOk = false;
unsigned long packetId = 0;
unsigned long lastSend = 0;

float readBatteryVoltage() {
  uint32_t mv = 0;
  for (int i = 0; i < 16; i++) mv += analogReadMilliVolts(BATTERY_ADC_PIN);
  return (mv / 16.0f) / 1000.0f * DIVIDER_RATIO;
}

bool readTemperature(float& out) {
  // TODO: read the team's temperature sensor here. Return false if the read fails,
  // and the packet will carry "temperature_c":null so the dashboard flags a sensor fault.
  return false;
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) delay(250);
  if (WiFi.status() == WL_CONNECTED) configTime(0, 0, "pool.ntp.org", "time.google.com");  // UTC
}

void connectMqtt() {
  if (mqtt.connected() || WiFi.status() != WL_CONNECTED) return;
  String id = String("ku-siraj-esp32-") + String((uint32_t)ESP.getEfuseMac(), HEX);
  // Last will: the broker marks us offline if the ESP32 drops off.
  if (mqtt.connect(id.c_str(), STATUS_TOPIC, 1, true, "{\"state\":\"offline\"}")) {
    mqtt.publish(STATUS_TOPIC, "{\"state\":\"online\",\"source\":\"esp32 wifi\"}", true);
  }
}

void timestamp(char* buf, size_t n) {
  time_t now = time(nullptr);
  if (now < 1700000000) { buf[0] = 0; return; }          // clock not set yet: leave timestamp out
  struct tm t; gmtime_r(&now, &t);
  strftime(buf, n, "%Y-%m-%dT%H:%M:%SZ", &t);
}

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);
  inaOk = ina219.begin();
  analogReadResolution(12);
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(768);   // default 256 bytes is too small for one packet
  connectWiFi();
}

void loop() {
  connectWiFi();
  connectMqtt();
  mqtt.loop();
  if (millis() - lastSend < 1000) return;
  lastSend = millis();
  packetId++;

  char ts[24]; timestamp(ts, sizeof ts);
  char body[600];
  int n = snprintf(body, sizeof body, "{\"device_id\":\"%s\",\"packet_id\":%lu", DEVICE_ID, packetId);
  if (ts[0]) n += snprintf(body + n, sizeof body - n, ",\"timestamp\":\"%s\"", ts);
  n += snprintf(body + n, sizeof body - n, ",\"telemetry_source\":\"ESP32 %s\"", WiFi.status() == WL_CONNECTED ? "Wi-Fi" : "serial");

  // Load branch from the INA219 (null when the sensor does not answer).
  if (inaOk) {
    float busV = ina219.getBusVoltage_V() + ina219.getShuntVoltage_mV() / 1000.0f;
    float mA = ina219.getCurrent_mA();
    n += snprintf(body + n, sizeof body - n, ",\"load_voltage_v\":%.3f,\"load_current_ma\":%.1f", busV, mA);
  } else {
    n += snprintf(body + n, sizeof body - n, ",\"load_voltage_v\":null,\"load_current_ma\":null");
  }

  float vb = readBatteryVoltage();
  n += snprintf(body + n, sizeof body - n, ",\"battery_voltage_v\":%.3f", vb);

  if (HAS_TEMP_SENSOR) {
    float tc;
    if (readTemperature(tc)) n += snprintf(body + n, sizeof body - n, ",\"temperature_c\":%.1f", tc);
    else n += snprintf(body + n, sizeof body - n, ",\"temperature_c\":null");
  }

  if (WiFi.status() == WL_CONNECTED) n += snprintf(body + n, sizeof body - n, ",\"wifi_rssi_dbm\":%d", WiFi.RSSI());
  // Add lora_rssi_dbm here once the SX1278 ground receiver reports it.
  snprintf(body + n, sizeof body - n, ",\"simulated\":false}");

  Serial.println(body);                       // USB path (server.py / mqtt_publisher.py --serial)
  if (mqtt.connected()) mqtt.publish(TOPIC, body, true);   // Wi-Fi path, retained
}
