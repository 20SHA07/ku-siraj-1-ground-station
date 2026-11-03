/*
  KU-SIRAJ 1 - GROUND side: ESP32 + SX1278 (Ra-02, 433 MHz) LoRa receiver

  Receives the satellite's LoRa packets, adds the signal strength the ground radio measured
  (lora_rssi_dbm, lora_snr_db) and prints one JSON line per packet to USB serial.

  Then on the laptop:   ground\run_mqtt.bat COM5     -> dashboard link updates live
  (or, offline:         ground\run_usb_bridge.bat COM5 -> "USB bridge" mode)

  Same wiring as the satellite board:
    NSS GPIO5, SCK GPIO18, MISO GPIO19, MOSI GPIO23, RST GPIO14, DIO0 GPIO26, 3.3 V only.
  Library: "LoRa" by Sandeep Mistry.
*/
#include <SPI.h>
#include <LoRa.h>

// ---- radio settings: MUST match lora_satellite_tx ----------------------
const long LORA_FREQ = 433E6;
const int  SF        = 9;
const long BANDWIDTH = 125E3;
const int  SYNC_WORD = 0x34;
// -------------------------------------------------------------------------
const int PIN_NSS = 5, PIN_RST = 14, PIN_DIO0 = 26;

void setup() {
  Serial.begin(115200);
  LoRa.setPins(PIN_NSS, PIN_RST, PIN_DIO0);
  while (!LoRa.begin(LORA_FREQ)) {
    Serial.println("{\"status\":\"lora init failed, check wiring\"}");
    delay(2000);
  }
  LoRa.setSpreadingFactor(SF);
  LoRa.setSignalBandwidth(BANDWIDTH);
  LoRa.setSyncWord(SYNC_WORD);
  LoRa.enableCrc();
  Serial.println("{\"status\":\"ground receiver ready\"}");
}

void loop() {
  int size = LoRa.parsePacket();
  if (size == 0) return;

  char buf[256];
  int len = 0;
  while (LoRa.available() && len < (int)sizeof(buf) - 1) buf[len++] = (char)LoRa.read();
  buf[len] = 0;

  // Only forward packets that look like one of ours: a JSON object.
  if (len < 2 || buf[0] != '{' || buf[len - 1] != '}') return;

  // Insert the ground-measured link quality before the closing brace.
  buf[len - 1] = 0;
  Serial.printf("%s,\"lora_rssi_dbm\":%d,\"lora_snr_db\":%.1f,\"telemetry_source\":\"LoRa 433 MHz\"}\n",
                buf, LoRa.packetRssi(), LoRa.packetSnr());
}
