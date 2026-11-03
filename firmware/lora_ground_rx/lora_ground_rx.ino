/*
  KU-SIRAJ 1 - GROUND side: ESP32 (DOIT DEVKIT V1) + RA-02 SX1278 433 MHz, RadioLib
  Receives the satellite's LoRa packets, adds the RSSI/SNR this radio measured, and prints
  one JSON line per packet on USB serial (115200 baud).

  Then on the laptop:  ground\run_mqtt.bat COM5   -> the dashboard link updates live.

  Same RA-02 wiring as the satellite board:
    NSS/CS GPIO5   DIO0 GPIO26   RST GPIO14   SCK GPIO18   MISO GPIO19   MOSI GPIO23
*/
#include <SPI.h>
#include <RadioLib.h>

// Radio settings: must match lora_satellite_tx.
const float FREQ_MHZ = 433.0;
const float BW_KHZ = 125.0;
const uint8_t SF = 9;
const uint8_t CR = 7;
const uint8_t SYNC_WORD = 0x12;

SX1278 radio = new Module(5, 26, 14, RADIOLIB_NC);

void setup() {
  Serial.begin(115200);
  delay(500);
  SPI.begin(18, 19, 23, 5);
  int state = radio.begin(FREQ_MHZ, BW_KHZ, SF, CR, SYNC_WORD);
  if (state != RADIOLIB_ERR_NONE) {
    Serial.printf("{\"status\":\"RA-02 init failed, code %d. Check wiring, power, antenna.\"}\n", state);
    while (true) delay(1000);
  }
  radio.setCRC(true);
  Serial.println("{\"status\":\"KU-SIRAJ 1 ground receiver ready\"}");
}

void loop() {
  String msg;
  int state = radio.receive(msg);   // waits for a packet (times out after a few seconds)
  if (state == RADIOLIB_ERR_RX_TIMEOUT) return;
  if (state != RADIOLIB_ERR_NONE) {
    Serial.printf("{\"status\":\"receive error %d\"}\n", state);   // e.g. CRC error from a corrupted packet
    return;
  }
  msg.trim();
  // Forward only packets that look like ours: a JSON object.
  if (msg.length() < 2 || !msg.startsWith("{") || !msg.endsWith("}")) return;
  msg.remove(msg.length() - 1);
  Serial.printf("%s,\"lora_rssi_dbm\":%.0f,\"lora_snr_db\":%.1f,\"telemetry_source\":\"LoRa 433 MHz\"}\n",
                msg.c_str(), radio.getRSSI(), radio.getSNR());
}
