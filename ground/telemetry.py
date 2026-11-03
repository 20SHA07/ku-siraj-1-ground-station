"""KU-SIRAJ 1 telemetry data contract, shared by server.py and mqtt_publisher.py.

One message = one JSON object = one timestamped snapshot.

Required: device_id (text), packet_id (integer, counts up by 1 per packet).
timestamp: ISO 8601 UTC. If the ESP32 has no clock, the publisher sets it on receipt.
A channel that is not wired is left out of the message.
A sensor that failed to read is sent as null (kept as None here, so the dashboard flags it).
"""
import json
import math
import random
import re
from datetime import datetime, timezone

NUMERIC_FIELDS = (
    "solar_voltage_v", "solar_current_ma", "solar_power_mw",
    "battery_voltage_v", "battery_current_ma",
    "pem_voltage_v", "pem_current_ma", "pem_power_mw",
    "load_voltage_v", "load_current_ma", "load_power_mw",
    "temperature_c", "lora_rssi_dbm", "wifi_rssi_dbm",
    "packet_success_pct", "orbit_phase_deg",
)
TEXT_FIELDS = ("device_id", "operating_mode", "telemetry_source")
SAFE_TEXT = re.compile(r"^[A-Za-z0-9 _.:/()+-]{1,60}$")
MAX_LINE = 8192


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_packet(data, default_device="ku-siraj-1", default_source=None):
    """Validate one packet (a JSON text line or a dict). Returns a clean dict or None."""
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8", errors="replace")
    if isinstance(data, str):
        line = data.strip()
        if not line or len(line) > MAX_LINE:
            return None
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            return None
    else:
        raw = data
    if not isinstance(raw, dict):
        return None

    packet = {}
    try:
        if raw.get("packet_id") is not None:
            packet["packet_id"] = max(0, int(raw["packet_id"]))
    except (TypeError, ValueError, OverflowError):
        pass

    ts = raw.get("timestamp")
    packet["timestamp"] = str(ts)[:64] if isinstance(ts, str) and ts else now_iso()

    for key in TEXT_FIELDS:
        value = raw.get(key)
        if isinstance(value, str) and SAFE_TEXT.fullmatch(value):
            packet[key] = value
    packet.setdefault("device_id", default_device)
    if default_source and "telemetry_source" not in packet:
        packet["telemetry_source"] = default_source

    measured = 0
    for key in NUMERIC_FIELDS:
        if key not in raw:
            continue  # not wired: leave it out
        value = raw[key]
        try:
            number = float(value)
            if not math.isfinite(number):
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            packet[key] = None  # sensor failed: keep as null so the dashboard flags it
            measured += 1
            continue
        if key == "packet_success_pct":
            number = min(100.0, max(0.0, number))
        packet[key] = number
        measured += 1

    packet["simulated"] = bool(raw.get("simulated", False))
    return packet if measured or "packet_id" in packet else None


class OrbitSimulator:
    """Synthetic packets from the team's Multisim power-path model through a 94-minute orbit.

    Every packet is marked simulated=True. fault() injects the Design Manual's test cases.
    """

    ORBIT_MIN = 94
    ECLIPSE_MIN = 35

    def __init__(self, device_id="ku-siraj-1-sim", start_minute=88, seed=None):
        self.rng = random.Random(seed)
        self.device_id = device_id
        self.minute = start_minute
        self.packet_id = 0
        self.drift = 0.0
        self.warm = 0.9
        self.drain = 0.0
        self.draining = False
        self.spike = 0.0
        self.sensor_failed = False
        self.drop_left = 0

    def fault(self, name):
        if name == "drain":
            self.draining = True
        elif name == "spike":
            self.spike = 35.0
        elif name == "link":
            self.drop_left = 12
        elif name == "sensor":
            self.sensor_failed = True
        elif name == "clear":
            self.draining, self.drain, self.spike, self.sensor_failed, self.drop_left = False, 0.0, 0.0, False, 0

    def _n(self):
        return self.rng.random() - 0.5

    def next(self):
        """Return the next packet, or None when a simulated link loss drops it."""
        half = self.ECLIPSE_MIN / self.ORBIT_MIN * 180
        self.minute = (self.minute + 1) % self.ORBIT_MIN
        angle = self.minute / self.ORBIT_MIN * 360
        from_shadow = min(abs(angle), abs(360 - angle))
        sun = max(0.0, min(1.0, (from_shadow - half) / 6 + 0.5))
        self.packet_id += 1
        self.drift = min(0.12, self.drift + 0.0022) if sun < 0.5 else max(0.0, self.drift - 0.004)
        self.warm += (sun - self.warm) * 0.09
        if self.draining:
            self.drain = min(0.75, self.drain + 0.012)
        self.spike *= 0.975
        bat_i = 81.5 - 76.3 * sun + self._n() * 0.8
        packet = {
            "device_id": self.device_id,
            "packet_id": self.packet_id,
            "timestamp": now_iso(),
            "telemetry_source": "Simulator (Multisim model)",
            "operating_mode": "SUNLIGHT" if sun >= 0.5 else "ECLIPSE",
            "orbit_phase_deg": round(angle, 1),
            "solar_voltage_v": round(4.98 * min(1, sun * 2.5) + self._n() * 0.03, 2) if sun > 0.02 else 0.0,
            "solar_current_ma": round(max(0.0, 79.6 * sun + self._n() * 0.8), 1),
            "battery_voltage_v": round(3.86 - 0.0009 * bat_i - self.drift - self.drain + self._n() * 0.004, 3),
            "battery_current_ma": round(bat_i, 1),
            "pem_voltage_v": round(0.6 + self._n() * 0.01, 3),
            "pem_current_ma": round(75 + self._n() * 2, 1),
            "load_voltage_v": round(3.41 + 0.11 * sun + self._n() * 0.006, 3),
            "load_current_ma": round(94.8 + 2.8 * sun + self._n() * 0.6, 1),
            "temperature_c": None if self.sensor_failed else round(17 + 13 * self.warm + self.spike + self._n() * 0.3, 1),
            "lora_rssi_dbm": round(-86 + 8 * math.sin(self.packet_id / 11) + self._n() * 4),
            "simulated": True,
        }
        if self.drop_left > 0:
            self.drop_left -= 1
            return None
        return packet
