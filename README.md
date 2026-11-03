# KU-SIRAJ 1 Ground Station

Live ground-station dashboard for **KU-SIRAJ 1**, Team KU-SHIHAB's hydrogen-assisted CubeSat power demonstrator (SatForge UAE 2026).

**Dashboard:** https://20sha07.github.io/ku-siraj-1-ground-station/

The page is read-only. It never switches power sources or controls hydrogen equipment, and it is not flight hardware. PEM figures are provisional until bench-verified. Anything simulated or replayed is labelled.

## Questions the dashboard answers in 5 seconds

| # | Operator question | Panel |
|---|---|---|
| 1 | Is the satellite healthy? | Health banner: NOMINAL / WARNING / CRITICAL / STALE / NO DATA, with the reason |
| 2 | Is the link alive, and how old is the data? | Header link and last-packet pills, LoRa signal chart, link chain, packet success |
| 3 | Which source is carrying the bus? | Power flow (solar, battery, PEM through their Schottky diodes) |
| 4 | Is the battery inside its limits? | Battery tile and voltage chart with warn/critical lines |
| 5 | Is the bay within temperature limits? | Temperature tile and chart with warn/critical lines |

## Architecture

```
SATELLITE                               GROUND STATION                              ANYONE WITH THE LINK
ESP32 + sensors + SX1278 ──LoRa 433 MHz──▶ ESP32 + SX1278 ──USB──▶ mqtt_publisher.py ──▶ MQTT broker ──wss──▶ dashboard
(lora_satellite_tx)                       (lora_ground_rx)          (run_mqtt.bat COMx)
                                                            └──USB──▶ server.py ──local WebSocket──▶ dashboard "USB bridge" (no internet)
```

The ground receiver adds the RSSI and SNR it measured to every packet, so the LoRa signal panel shows the real link. Without the radio, the satellite ESP32 can publish over Wi-Fi itself (`esp32_mqtt_telemetry`).

- **Transport:** MQTT. The ESP32 (or the laptop publisher) publishes one JSON packet per second to `ku-shihab/ku-siraj-1/telemetry`; the page subscribes. Packets are *retained*, so a new viewer sees the last packet at once, with its age.
- **Status:** the publisher sets `ku-shihab/ku-siraj-1/status` to `online`, and the broker sets it to `offline` (MQTT last will) if the publisher disappears.
- **Dashboard:** one static HTML file on GitHub Pages. Charts are drawn with Canvas and SVG, no chart library. MQTT in the browser uses mqtt.js.
- **Fallback:** if no live packet arrives within 8 s, the page runs the simulation, clearly labelled, and switches back to live as soon as a packet arrives.

## Run it

| Goal | Command (in `ground/`, Windows) |
|---|---|
| LoRa: satellite → ground receiver → link | flash `lora_satellite_tx` and `lora_ground_rx` (RadioLib, RA-02 on CS 5 / DIO0 26 / RST 14), plug the receiver into the laptop, `run_mqtt.bat COM5` |
| Live data from the ESP32 over USB, viewable by anyone through the link | `run_mqtt.bat COM5` |
| Live link without hardware (simulated orbit + fault tests) | `run_simulator.bat` |
| No internet: ESP32 over USB straight into this laptop's browser | `run_usb_bridge.bat COM5`, then choose **USB bridge** |
| ESP32 publishing by itself over Wi-Fi | flash `firmware/esp32_mqtt_telemetry` (set Wi-Fi name and password) |

Python 3.10+ and `py -m pip install -r requirements.txt` (pyserial, paho-mqtt, websockets).

On the page you can also open **Demo simulation** (with fault injection) or **Replay a log** (`.jsonl` or a CSV recorded by the page). `?mode=demo`, `?broker=…` and `?topic=…` in the URL preset these.

## Data contract

One message = one JSON object = one timestamped snapshot.

| Field | Type | Unit | Notes | Required |
|---|---|---|---|---|
| `device_id` | text | — | identifies the sender | ✓ |
| `packet_id` | integer | — | +1 per packet; gaps are counted as lost packets | ✓ |
| `timestamp` | text | ISO 8601 UTC | set by the ESP32 (NTP) or by the publisher on receipt | ✓ |
| `operating_mode` | text | — | e.g. `SUNLIGHT`, `ECLIPSE` | |
| `solar_voltage_v`, `solar_current_ma` | number | V, mA | solar branch | |
| `battery_voltage_v`, `battery_current_ma` | number | V, mA | current + = discharging | |
| `pem_voltage_v`, `pem_current_ma` | number | V, mA | provisional PEM cell | |
| `load_voltage_v`, `load_current_ma` | number | V, mA | load bus | |
| `*_power_mw` | number | mW | optional; otherwise V × mA | |
| `temperature_c` | number | °C | sensor model to be confirmed | |
| `lora_rssi_dbm`, `wifi_rssi_dbm` | number | dBm | link quality | |
| `packet_success_pct` | number | % | otherwise worked out from packet-ID gaps | |
| `orbit_phase_deg` | number | ° | 0 = centre of Earth's shadow (simulation) | |
| `simulated` | boolean | — | `true` for synthetic data | |

**Not wired** → leave the field out (shown as "Not sent"). **Sensor failed** → send `null` (shown as "Sensor fault").
One INA219 measures one shunt branch, so only send the currents the circuit really measures.

## Limits (provisional)

| Signal | Range accepted | Warning | Critical |
|---|---|---|---|
| Battery voltage | 2.5–4.5 V | < 3.5 V or > 4.2 V | < 3.3 V or > 4.25 V |
| Load bus voltage | 0–6 V | < 3.3 V | < 3.0 V |
| Load current | −5–300 mA | > 110 mA | > 130 mA |
| Solar current | −5–200 mA | > 85 mA (above rating) | — |
| PEM current | −5–150 mA | > 100 mA | — |
| Temperature | −40–125 °C | < 0 or > 40 °C | < −10 or > 45 °C |
| LoRa RSSI | −150–0 dBm | < −105 dBm | < −115 dBm |
| Packet success (last 100) | 0–100 % | < 95 % | < 80 % |
| Data age | — | — | stale after 5 s |

Readings outside the accepted range, `null` readings and a value stuck for 30 packets are flagged as sensor faults.

## Fault test plan

Run with **Demo simulation → Fault injection**, or `mqtt_publisher.py --simulate --faults` for the live path.

| Fault | Trigger | Expected reaction | Result |
|---|---|---|---|
| Battery falling | −0.012 V per packet | Battery tile amber below 3.5 V, banner CRITICAL below 3.3 V, event + chart marker | Pass |
| Temperature spike | +35 °C jump | Temperature tile/banner CRITICAL above 45 °C, marker on chart | Pass |
| Link lost | no packets for 12 s | After 5 s: banner STALE, values greyed, "Last packet 7 s ago", gap in charts; missing IDs counted after | Pass |
| Sensor failure | `temperature_c: null` | Tile "Sensor fault", banner WARNING, limits table shows `null` | Pass |
| Live packet after fallback | first fresh MQTT packet | Simulation stops, page switches to live | Pass |

Tested in headless Chromium with a stubbed broker, and end to end through broker.hivemq.com from the live site. The ESP32 and LoRa sketches have not been run on the team's boards.

## Security notes

- The default broker (`broker.hivemq.com`) is a free public **test** broker: anyone who knows the topic can read or publish to it. The page validates every packet, never sends anything, and shows only what arrives. Do not send secrets.
- Wi-Fi passwords belong in the firmware on the team's machines, not in this public repo.

## Files

- `index.html` — the dashboard
- `ground/` — `telemetry.py` (data contract + simulator), `mqtt_publisher.py`, `server.py` (USB bridge), launchers
- `firmware/lora_satellite_tx/`, `firmware/lora_ground_rx/` — SX1278 LoRa link (satellite transmitter, ground receiver)
- `firmware/esp32_mqtt_telemetry/` — ESP32 Wi-Fi + serial example
- `examples/` — sample logs for **Replay a log**
